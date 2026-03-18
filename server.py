from __future__ import annotations

import csv
import html
import ipaddress
import io
import json
import os
import re
import socket
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
HOST = "0.0.0.0"
PORT = 4173
READ_TIMEOUT_SECONDS = 20
GOOGLE_SHEETS_HOSTS = {"docs.google.com"}

SOURCE_KIND_SIGNAL = {"id": "sinalizacao", "label": "Aba principal de Sinalizacao"}
SOURCE_KIND_MEASUREMENT = {"id": "medicao", "label": "Aba de Medicao"}
SOURCE_KIND_AUXILIARY = {"id": "valores_minimos", "label": "Aba auxiliar"}
SOURCE_KIND_UNKNOWN = {"id": "desconhecida", "label": "Aba nao identificada"}
UNKNOWN_MONITORING = {"id": "desconhecida", "label": "Monitoracao nao identificada"}


@dataclass(frozen=True)
class SheetReference:
    spreadsheet_id: str
    gid: str


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    lowered = without_accents.casefold()
    return re.sub(r"[^a-z0-9]+", "", lowered)


def normalize_label(value: str) -> str:
    return " ".join((value or "").strip().split())


def clean_cell(value: str) -> str:
    return normalize_label(value or "")


def normalize_identifier(value: str) -> str:
    text = clean_cell(value)
    if not text:
        return ""

    compact = text.replace(" ", "")
    if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?", compact):
        normalized_numeric = compact.replace(",", ".")
        try:
            decimal_value = Decimal(normalized_numeric)
            if decimal_value == decimal_value.to_integral_value():
                return str(decimal_value.to_integral_value())
            normalized = format(decimal_value.normalize(), "f").rstrip("0").rstrip(".")
            return normalized or "0"
        except (InvalidOperation, ValueError):
            return compact
    return compact


def safe_sort_key(value: str) -> tuple[str, str]:
    return normalize_text(value), value or ""


def resolve_server_host() -> str:
    host = (os.environ.get("PAINEL_HOST") or HOST).strip()
    return host or HOST


def resolve_server_port() -> int:
    raw_port = (os.environ.get("PAINEL_PORT") or str(PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit(f"PAINEL_PORT invalida: {raw_port!r}. Use um numero entre 1 e 65535.") from exc

    if not 1 <= port <= 65535:
        raise SystemExit(f"PAINEL_PORT fora da faixa valida: {port}.")

    return port


def is_private_ipv4(address: str) -> bool:
    try:
        candidate = ipaddress.ip_address(address)
    except ValueError:
        return False
    return candidate.version == 4 and candidate.is_private and not candidate.is_loopback and not candidate.is_link_local


def discover_lan_ipv4() -> list[str]:
    addresses: set[str] = set()

    try:
        hostname = socket.gethostname()
        for _family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            if sockaddr and is_private_ipv4(sockaddr[0]):
                addresses.add(sockaddr[0])
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
            if is_private_ipv4(candidate):
                addresses.add(candidate)
    except OSError:
        pass

    return sorted(addresses, key=lambda item: tuple(int(part) for part in item.split(".")))


def build_access_urls(host: str, port: int) -> list[str]:
    if host in {"0.0.0.0", "::"}:
        urls = [f"http://127.0.0.1:{port}"]
        urls.extend(f"http://{ip}:{port}" for ip in discover_lan_ipv4())
        return urls
    return [f"http://{host}:{port}"]


def extract_sheet_reference(raw_url: str) -> SheetReference:
    if not raw_url or not raw_url.strip():
        raise ValueError("Informe um link de planilha do Google.")

    parsed = urllib.parse.urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("O link precisa comecar com http:// ou https://.")

    if parsed.netloc not in GOOGLE_SHEETS_HOSTS:
        raise ValueError("Use um link do Google Planilhas.")

    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", parsed.path)
    if not match:
        raise ValueError("Nao encontrei o identificador da planilha no link informado.")

    query = urllib.parse.parse_qs(parsed.query)
    gid = query.get("gid", [None])[0]
    if not gid and parsed.fragment:
        fragment = urllib.parse.parse_qs(parsed.fragment)
        gid = fragment.get("gid", [None])[0]

    return SheetReference(spreadsheet_id=match.group(1), gid=gid or "0")


def download_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PainelGestaoMonitoracao/2.0",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
    )

    with urllib.request.urlopen(request, timeout=READ_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        payload = response.read()
        return payload.decode(charset, errors="replace")


def fetch_workbook_metadata(reference: SheetReference, metadata_cache: dict[str, dict[str, object]]) -> dict[str, object]:
    cached = metadata_cache.get(reference.spreadsheet_id)
    if cached:
        return cached

    workbook_url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{reference.spreadsheet_id}/edit?gid={reference.gid}"
    )
    page = download_text(workbook_url)

    title_match = re.search(r"<title>(.*?)</title>", page, flags=re.IGNORECASE | re.DOTALL)
    workbook_name = "Banco sem nome identificado"
    if title_match:
        workbook_name = html.unescape(title_match.group(1)).strip()
        workbook_name = re.sub(r"\s*-\s*Google Planilhas\s*$", "", workbook_name).strip()
        workbook_name = workbook_name or "Banco sem nome identificado"

    tabs: list[dict[str, object]] = []
    tab_pattern = re.compile(r'\[21350203,"\[(\d+),0,\\"([^\\"]+)\\",\[\{\\"1\\":\[\[0,0,\\"([^\\"]+)\\"')
    for index, gid, name in tab_pattern.findall(page):
        tabs.append(
            {
                "index": int(index),
                "gid": gid,
                "name": html.unescape(name),
            }
        )

    metadata = {
        "workbookName": workbook_name,
        "tabs": tabs,
    }
    metadata_cache[reference.spreadsheet_id] = metadata
    return metadata


def fetch_sheet_rows(reference: SheetReference) -> tuple[list[str], list[dict[str, str]]]:
    csv_url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{reference.spreadsheet_id}/export?format=csv&gid={reference.gid}"
    )
    csv_text = download_text(csv_url).lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = [normalize_label(header) for header in reader.fieldnames or [] if header and normalize_label(header)]

    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {normalize_label(key): clean_cell(value) for key, value in row.items() if key}
        if any(cleaned.values()):
            rows.append(cleaned)

    return headers, rows


def find_header(headers: list[str], normalized_name: str) -> str | None:
    return next((header for header in headers if normalize_text(header) == normalized_name), None)


def detect_source_kind(headers: list[str]) -> dict[str, str]:
    normalized_headers = {normalize_text(header) for header in headers}

    signal_headers = {"id", "statusdocadastro", "rodovia", "km", "uf", "sentido", "codigooutipo"}
    measurement_headers = {"id", "tipopelicula", "cor", "registro", "resultado"}
    auxiliary_headers = {"cor", "tipoi", "tipoii", "tipoiii"}

    if signal_headers.issubset(normalized_headers):
        return SOURCE_KIND_SIGNAL
    if measurement_headers.issubset(normalized_headers):
        return SOURCE_KIND_MEASUREMENT
    if auxiliary_headers.issubset(normalized_headers):
        return SOURCE_KIND_AUXILIARY
    return SOURCE_KIND_UNKNOWN


def detect_monitoring_type(workbook_name: str, headers: list[str], source_kind: dict[str, str]) -> dict[str, str]:
    if source_kind["id"] != SOURCE_KIND_SIGNAL["id"]:
        return UNKNOWN_MONITORING

    normalized_name = normalize_text(workbook_name)
    normalized_headers = {normalize_text(header) for header in headers}
    title_matches = any(
        keyword in normalized_name
        for keyword in ("monitoramentosinalizacaov", "sinalizacaov", "sinalizacaovertical")
    )
    header_matches = {"rodovia", "km", "uf", "sentido", "codigooutipo"}.issubset(normalized_headers)

    if title_matches or header_matches:
        return {
            "id": "sinalizacao_vertical",
            "label": "Monitoracao de Sinalizacao Vertical",
        }

    return UNKNOWN_MONITORING


def filter_rows_with_non_empty_id(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    id_header = find_header(headers, "id")
    if not id_header:
        return rows
    return [row for row in rows if clean_cell(row.get(id_header, ""))]


def extract_roads(headers: list[str], rows: list[dict[str, str]]) -> list[str]:
    road_header = find_header(headers, "rodovia")
    if not road_header:
        return []
    roads = {clean_cell(row.get(road_header, "")) for row in rows if clean_cell(row.get(road_header, ""))}
    return sorted(roads, key=safe_sort_key)


def get_tab_name(metadata: dict[str, object], gid: str) -> str:
    tabs = metadata.get("tabs", [])
    for tab in tabs:
        if str(tab.get("gid")) == str(gid):
            return str(tab.get("name"))
    return f"Aba {gid}"


def build_source_preview(
    sheet_url: str,
    metadata_cache: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    cache = metadata_cache if metadata_cache is not None else {}
    reference = extract_sheet_reference(sheet_url)
    metadata = fetch_workbook_metadata(reference, cache)
    headers, rows = fetch_sheet_rows(reference)

    if not headers:
        raise ValueError("A planilha nao possui cabecalhos legiveis.")

    source_kind = detect_source_kind(headers)
    monitoring_type = detect_monitoring_type(str(metadata["workbookName"]), headers, source_kind)
    imported_rows = filter_rows_with_non_empty_id(headers, rows)
    tab_name = get_tab_name(metadata, reference.gid)

    return {
        "sheetUrl": sheet_url,
        "databaseName": metadata["workbookName"],
        "tabName": tab_name,
        "displayName": f"{metadata['workbookName']} / {tab_name}",
        "monitoringType": monitoring_type,
        "sourceKind": source_kind,
        "roads": extract_roads(headers, imported_rows),
        "rowCount": len(imported_rows),
        "rawRowCount": len(rows),
        "headers": headers,
        "sheetReference": {
            "spreadsheetId": reference.spreadsheet_id,
            "gid": reference.gid,
        },
    }


def format_meter_value(value: str) -> str:
    raw = clean_cell(value)
    if not raw:
        return "000"

    digits = re.sub(r"\D", "", raw)
    if digits:
        return digits[-3:].zfill(3)
    return raw


def format_km_value(value: str) -> str:
    raw = clean_cell(value)
    if not raw:
        return "0"
    if re.fullmatch(r"\d+[.,]0+", raw):
        return re.split(r"[.,]", raw)[0]
    return raw


def format_road_value(value: str) -> str:
    raw = clean_cell(value).upper()
    if raw.startswith("BR-"):
        return raw[3:]
    if raw.startswith("BR"):
        return raw[2:]
    return raw


def format_ficha(record: dict[str, str]) -> str:
    uf = clean_cell(record.get("UF", "")).upper() or "SEM_UF"
    road = format_road_value(record.get("Rodovia", ""))
    km = format_km_value(record.get("Km", ""))
    meter = format_meter_value(record.get("KmMetragem", ""))
    direction = (clean_cell(record.get("Sentido", ""))[:1] or "?").upper()
    numerador = clean_cell(record.get("Numerador", "")) or "-"
    return f"{uf} {road} {km}+{meter} {direction} {numerador}"


def parse_boolean_text(value: str) -> bool | None:
    normalized = normalize_text(value)
    if normalized in {"true", "verdadeiro"}:
        return True
    if normalized in {"false", "falso"}:
        return False
    return None


def preserve_unique_sorted(values: list[str]) -> list[str]:
    unique_values = {clean_cell(value) for value in values if clean_cell(value)}
    return sorted(unique_values, key=safe_sort_key)


def join_display_values(values: list[str], empty_label: str) -> str:
    if not values:
        return empty_label
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} e {values[1]}"
    return ", ".join(values[:-1]) + f" e {values[-1]}"


def as_formatted_number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def group_records_by_uf(records: list[dict[str, str]]) -> list[dict[str, object]]:
    by_uf: dict[str, list[str]] = defaultdict(list)
    for record in records:
        uf = clean_cell(record.get("UF", "")) or "Sem UF"
        ficha = clean_cell(record.get("FICHA", ""))
        if ficha:
            by_uf[uf].append(ficha)

    groups = []
    for uf in sorted(by_uf, key=safe_sort_key):
        fichas = sorted(set(by_uf[uf]), key=safe_sort_key)
        groups.append({"uf": uf, "items": fichas})
    return groups


def create_drilldown(
    drilldowns: dict[str, dict[str, object]],
    key: str,
    title: str,
    records: list[dict[str, str]],
) -> None:
    drilldowns[key] = {
        "title": title,
        "total": len(records),
        "groups": group_records_by_uf(records),
    }


def build_signal_records(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, str]]:
    id_header = find_header(headers, "id")
    if not id_header:
        raise ValueError("A fonte principal nao possui a coluna ID.")

    field_map = {
        "ID": id_header,
        "UF": find_header(headers, "uf"),
        "Rodovia": find_header(headers, "rodovia"),
        "Km": find_header(headers, "km"),
        "KmMetragem": find_header(headers, "kmmetragem"),
        "Sentido": find_header(headers, "sentido"),
        "Numerador": find_header(headers, "numerador"),
        "StatusDoCadastro": find_header(headers, "statusdocadastro"),
        "CodigoOuTipo": find_header(headers, "codigooutipo"),
        "Largura": find_header(headers, "largura"),
        "Altura": find_header(headers, "altura"),
        "Observacoes": find_header(headers, "observacoes"),
    }

    records: list[dict[str, str]] = []
    for row in rows:
        record_id = normalize_identifier(row.get(field_map["ID"], ""))
        if not record_id:
            continue

        record = {key: clean_cell(row.get(header, "")) if header else "" for key, header in field_map.items()}
        record["ID"] = record_id
        record["FICHA"] = format_ficha(record)
        record["Observacoes"] = record["Observacoes"] or "Sem Observacoes"
        record["StatusDoCadastro"] = record["StatusDoCadastro"] or "Sem Status"
        record["CodigoOuTipo"] = record["CodigoOuTipo"] or "Sem CodigoOuTipo"
        record["UF"] = record["UF"] or "Sem UF"
        record["Largura"] = record["Largura"] or "Sem largura"
        record["Altura"] = record["Altura"] or "Sem altura"
        records.append(record)

    return records


def build_measurement_rows(headers: list[str], rows: list[dict[str, str]]) -> list[dict[str, object]]:
    id_header = find_header(headers, "id")
    if not id_header:
        return []

    film_header = find_header(headers, "tipopelicula")
    color_header = find_header(headers, "cor")
    registro_header = find_header(headers, "registro")
    result_header = find_header(headers, "resultado")

    measurements: list[dict[str, object]] = []
    for row in rows:
        measurement_id = normalize_identifier(row.get(id_header, ""))
        if not measurement_id:
            continue

        result_text = clean_cell(row.get(result_header, "")) if result_header else ""
        measurements.append(
            {
                "ID": measurement_id,
                "TipoPelicula": clean_cell(row.get(film_header, "")) if film_header else "",
                "Cor": clean_cell(row.get(color_header, "")) if color_header else "",
                "Registro": normalize_identifier(row.get(registro_header, "")) if registro_header else "",
                "Resultado": result_text,
                "ResultadoBool": parse_boolean_text(result_text),
            }
        )

    return measurements


def build_counter_items(
    values_to_records: dict[str, list[dict[str, str]]],
    title_prefix: str,
    drilldowns: dict[str, dict[str, object]],
    key_prefix: str,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for label in sorted(values_to_records, key=safe_sort_key):
        records = values_to_records[label]
        drilldown_key = f"{key_prefix}::{normalize_text(label) or 'vazio'}"
        create_drilldown(drilldowns, drilldown_key, f"{title_prefix}: {label}", records)
        items.append(
            {
                "label": label,
                "value": len(records),
                "valueFormatted": as_formatted_number(len(records)),
                "drilldownKey": drilldown_key,
            }
        )
    return items


def format_dimension_combination(width: str, height: str) -> str:
    clean_width = clean_cell(width) or "Sem largura"
    clean_height = clean_cell(height) or "Sem altura"
    if clean_width.startswith("Sem ") or clean_height.startswith("Sem "):
        return f"{clean_width} x {clean_height}"
    return f"{clean_width} x {clean_height} m"


def build_grouped_dimension_items(
    records: list[dict[str, str]],
    drilldowns: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    dimension_index: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    grouped_dimensions: dict[str, list[dict[str, object]]] = defaultdict(list)

    for record in records:
        dimension_index[(record["CodigoOuTipo"], record["Largura"], record["Altura"])].append(record)

    sorted_dimensions = sorted(
        dimension_index,
        key=lambda item: (
            safe_sort_key(item[0])[0],
            safe_sort_key(item[1])[0],
            safe_sort_key(item[2])[0],
        ),
    )

    for code, width, height in sorted_dimensions:
        grouped_records = dimension_index[(code, width, height)]
        dimension_label = format_dimension_combination(width, height)
        drilldown_key = f"dimensoes::{normalize_text(code)}::{normalize_text(width)}::{normalize_text(height)}"
        create_drilldown(drilldowns, drilldown_key, f"{code} - Dimensoes {dimension_label}", grouped_records)
        grouped_dimensions[code].append(
            {
                "label": dimension_label,
                "value": len(grouped_records),
                "valueFormatted": as_formatted_number(len(grouped_records)),
                "drilldownKey": drilldown_key,
            }
        )

    return [{"group": group, "items": grouped_dimensions[group]} for group in sorted(grouped_dimensions, key=safe_sort_key)]


def compute_vertical_dashboard(previews: list[dict[str, object]]) -> dict[str, object]:
    source_by_kind: dict[str, list[dict[str, object]]] = defaultdict(list)
    for preview in previews:
        source_by_kind[str(preview["sourceKind"]["id"])].append(preview)

    signal_preview = next(
        (
            preview
            for preview in previews
            if preview.get("isPrimary") and preview["sourceKind"]["id"] == SOURCE_KIND_SIGNAL["id"]
        ),
        None,
    )
    if not signal_preview:
        signal_preview = source_by_kind[SOURCE_KIND_SIGNAL["id"]][0] if source_by_kind[SOURCE_KIND_SIGNAL["id"]] else None

    if not signal_preview:
        raise ValueError("Nao foi encontrada uma fonte principal de Sinalizacao para montar o dashboard.")

    measurement_preview = source_by_kind[SOURCE_KIND_MEASUREMENT["id"]][0] if source_by_kind[SOURCE_KIND_MEASUREMENT["id"]] else None
    issues: list[str] = []
    if not measurement_preview:
        issues.append("Nenhuma fonte de Medicao foi vinculada. As analises de afericao nao estarao disponiveis.")

    signal_reference = extract_sheet_reference(str(signal_preview["sheetUrl"]))
    signal_headers, signal_rows = fetch_sheet_rows(signal_reference)
    signal_records = build_signal_records(signal_headers, signal_rows)

    measurement_rows: list[dict[str, object]] = []
    if measurement_preview:
        measurement_reference = extract_sheet_reference(str(measurement_preview["sheetUrl"]))
        measurement_headers, measurement_raw_rows = fetch_sheet_rows(measurement_reference)
        measurement_rows = build_measurement_rows(measurement_headers, measurement_raw_rows)

    measurement_by_registro: dict[str, list[dict[str, object]]] = defaultdict(list)
    for measurement in measurement_rows:
        registro = normalize_identifier(str(measurement.get("Registro", "")))
        if registro:
            measurement_by_registro[registro].append(measurement)

    measured_records = [record for record in signal_records if measurement_by_registro.get(record["ID"])]
    unmeasured_records = [record for record in signal_records if not measurement_by_registro.get(record["ID"])]

    status_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    type_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    observation_groups: dict[str, list[dict[str, str]]] = defaultdict(list)

    for record in signal_records:
        status_groups[record["StatusDoCadastro"]].append(record)
        type_groups[record["CodigoOuTipo"]].append(record)
        observation_groups[record["Observacoes"]].append(record)

    drilldowns: dict[str, dict[str, object]] = {}

    create_drilldown(drilldowns, "total-fichas", "Total de Fichas", signal_records)
    create_drilldown(drilldowns, "placas-com-medicao", "Placas Com Medicao", measured_records)
    create_drilldown(drilldowns, "placas-sem-medicao", "Placas Sem Medicao", unmeasured_records)

    status_fichas = build_counter_items(status_groups, "Status das Fichas", drilldowns, "status-fichas")
    tipos_placas = build_counter_items(type_groups, "Tipos de Placas Registradas", drilldowns, "tipos-placas")
    dimensoes_registradas = build_grouped_dimension_items(signal_records, drilldowns)
    observacoes = build_counter_items(observation_groups, "Observacoes", drilldowns, "observacoes")

    quantity_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    film_color_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    approvals = {"RetroRefletancia Aprovada": [], "RetroRefletancia Reprovada": []}

    if measurement_preview:
        quantity_index: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
        film_color_index: dict[tuple[str, tuple[str, ...], tuple[str, ...]], list[dict[str, str]]] = defaultdict(list)

        for record in measured_records:
            related_measurements = measurement_by_registro[record["ID"]]
            measurement_count = len(related_measurements)
            quantity_index[(record["CodigoOuTipo"], measurement_count)].append(record)

            colors = preserve_unique_sorted([str(item.get("Cor", "")) for item in related_measurements])
            film_types = preserve_unique_sorted([str(item.get("TipoPelicula", "")) for item in related_measurements])
            film_color_index[(record["CodigoOuTipo"], tuple(colors), tuple(film_types))].append(record)

            results = [item.get("ResultadoBool") for item in related_measurements]
            has_false = any(result is False for result in results)
            has_true = any(result is True for result in results)
            if has_false:
                approvals["RetroRefletancia Reprovada"].append(record)
            elif has_true:
                approvals["RetroRefletancia Aprovada"].append(record)
            else:
                approvals["RetroRefletancia Reprovada"].append(record)

        for code, measurement_count in sorted(quantity_index, key=lambda item: (safe_sort_key(item[0])[0], item[1])):
            records = quantity_index[(code, measurement_count)]
            drilldown_key = f"quantidade-aferida::{normalize_text(code)}::{measurement_count}"
            create_drilldown(drilldowns, drilldown_key, f"{code} - {measurement_count} Medicoes", records)
            quantity_groups[code].append(
                {
                    "label": f"{measurement_count} Medicoes",
                    "value": len(records),
                    "valueFormatted": as_formatted_number(len(records)),
                    "drilldownKey": drilldown_key,
                }
            )

        sorted_film_groups = sorted(
            film_color_index,
            key=lambda item: (
                safe_sort_key(item[0])[0],
                safe_sort_key(" ".join(item[1]))[0],
                safe_sort_key(" ".join(item[2]))[0],
            ),
        )
        for code, colors, film_types in sorted_film_groups:
            records = film_color_index[(code, colors, film_types)]
            drilldown_key = (
                "pelicula-cor::"
                f"{normalize_text(code)}::{normalize_text(' '.join(colors))}::{normalize_text(' '.join(film_types))}"
            )
            create_drilldown(drilldowns, drilldown_key, f"{code} - Tipos de Pelicula e Cor", records)
            film_color_groups[code].append(
                {
                    "label": f"Cores: {join_display_values(list(colors), 'Sem cor')}",
                    "details": [f"Peliculas: {join_display_values(list(film_types), 'Sem pelicula')}"],
                    "value": len(records),
                    "valueFormatted": as_formatted_number(len(records)),
                    "drilldownKey": drilldown_key,
                }
            )

        for approval_label, records in approvals.items():
            drilldown_key = f"aprovacoes::{normalize_text(approval_label)}"
            create_drilldown(drilldowns, drilldown_key, approval_label, records)

    grouped_quantity = [{"group": group, "items": quantity_groups[group]} for group in sorted(quantity_groups, key=safe_sort_key)]
    grouped_film_color = [{"group": group, "items": film_color_groups[group]} for group in sorted(film_color_groups, key=safe_sort_key)]

    approvals_items = []
    for approval_label in ("RetroRefletancia Aprovada", "RetroRefletancia Reprovada"):
        records = approvals.get(approval_label, [])
        approvals_items.append(
            {
                "label": approval_label,
                "value": len(records),
                "valueFormatted": as_formatted_number(len(records)),
                "drilldownKey": f"aprovacoes::{normalize_text(approval_label)}" if records else None,
            }
        )

    summary_cards = [
        {
            "label": "Total de Fichas",
            "value": len(signal_records),
            "valueFormatted": as_formatted_number(len(signal_records)),
            "drilldownKey": "total-fichas",
        }
    ]

    sections = [
        {"id": "status-fichas", "title": "Status das Fichas", "type": "list", "items": status_fichas},
        {
            "id": "status-afericao",
            "title": "Status da Afericao",
            "type": "subsections",
            "subsections": [
                {
                    "id": "placas-aferidas",
                    "title": "Placas Aferidas",
                    "type": "list",
                    "items": [
                        {
                            "label": "Placas Com Medicao",
                            "value": len(measured_records),
                            "valueFormatted": as_formatted_number(len(measured_records)),
                            "drilldownKey": "placas-com-medicao",
                        },
                        {
                            "label": "Placas Sem Medicao",
                            "value": len(unmeasured_records),
                            "valueFormatted": as_formatted_number(len(unmeasured_records)),
                            "drilldownKey": "placas-sem-medicao",
                        },
                    ],
                },
                {
                    "id": "quantidade-aferida-placa",
                    "title": "Quantidade Aferida/Placa",
                    "type": "grouped-list",
                    "groups": grouped_quantity,
                    "emptyMessage": "Nao ha placas com Medicao para consolidar." if not grouped_quantity else None,
                },
                {
                    "id": "tipos-pelicula-cor",
                    "title": "Tipos de Pelicula e Cor",
                    "type": "grouped-list",
                    "groups": grouped_film_color,
                    "emptyMessage": "Nao ha combinacoes de Cor e Pelicula disponiveis." if not grouped_film_color else None,
                },
                {"id": "aprovacoes", "title": "Aprovacoes", "type": "list", "items": approvals_items},
            ],
        },
        {"id": "tipos-placas", "title": "Tipos de Placas Registradas", "type": "list", "items": tipos_placas},
        {
            "id": "dimensoes-registradas",
            "title": "Dimensoes Registradas",
            "type": "grouped-list",
            "groups": dimensoes_registradas,
            "emptyMessage": "Nao ha combinacoes de Largura e Altura disponiveis." if not dimensoes_registradas else None,
        },
        {"id": "observacoes", "title": "Observacoes", "type": "list", "items": observacoes},
    ]

    return {
        "monitoringType": signal_preview["monitoringType"],
        "databaseName": signal_preview["databaseName"],
        "tabName": signal_preview["tabName"],
        "roads": signal_preview["roads"],
        "sources": previews,
        "summaryCards": summary_cards,
        "sections": sections,
        "drilldowns": drilldowns,
        "issues": issues,
    }


def build_dashboard(payload: dict[str, object]) -> dict[str, object]:
    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("Nenhuma fonte foi informada para montar o dashboard.")

    cache: dict[str, dict[str, object]] = {}
    previews: list[dict[str, object]] = []

    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            continue
        sheet_url = clean_cell(str(raw_source.get("sheetUrl", "")))
        if not sheet_url:
            continue

        preview = build_source_preview(sheet_url, cache)
        preview["slot"] = clean_cell(str(raw_source.get("slot", ""))) or f"fonte-{index + 1}"
        preview["isPrimary"] = bool(raw_source.get("isPrimary")) or index == 0
        previews.append(preview)

    if not previews:
        raise ValueError("Nenhuma fonte valida foi informada para montar o dashboard.")

    primary_preview = next((preview for preview in previews if preview.get("isPrimary")), previews[0])
    monitoring_type = primary_preview["monitoringType"]
    if monitoring_type["id"] == "sinalizacao_vertical":
        return compute_vertical_dashboard(previews)

    raise ValueError("O dashboard ainda nao foi implementado para essa monitoracao.")


class PainelRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_POST(self) -> None:
        routes = {
            "/api/analyze-sheet": self.handle_analyze_sheet,
            "/api/dashboard-data": self.handle_dashboard_data,
        }
        handler = routes.get(self.path)
        if not handler:
            self.send_error(HTTPStatus.NOT_FOUND, "Rota nao encontrada.")
            return
        handler()

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Use POST para consultar a API.")
            return
        super().do_GET()

    def read_json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        try:
            return json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Corpo da requisicao invalido.") from exc

    def handle_analyze_sheet(self) -> None:
        try:
            payload = self.read_json_body()
            sheet_url = clean_cell(str(payload.get("url", "")))
            result = build_source_preview(sheet_url)
            self.send_json(HTTPStatus.OK, result)
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": self.map_http_error(exc)})
        except urllib.error.URLError:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "Nao foi possivel acessar a planilha. Verifique a conexao e tente novamente."},
            )
        except Exception:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Ocorreu um erro interno ao analisar a planilha."},
            )

    def handle_dashboard_data(self) -> None:
        try:
            payload = self.read_json_body()
            result = build_dashboard(payload)
            self.send_json(HTTPStatus.OK, result)
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except urllib.error.HTTPError as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": self.map_http_error(exc)})
        except urllib.error.URLError:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "Nao foi possivel acessar uma das planilhas. Verifique a conexao e tente novamente."},
            )
        except Exception:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "Ocorreu um erro interno ao montar o dashboard."},
            )

    @staticmethod
    def map_http_error(exc: urllib.error.HTTPError) -> str:
        if exc.code == HTTPStatus.NOT_FOUND:
            return "A planilha nao foi encontrada."
        if exc.code in {HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED}:
            return "A planilha nao esta acessivel para leitura."
        return "Falha ao consultar a planilha informada."

    def send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response)


def main() -> None:
    if not STATIC_DIR.exists():
        raise SystemExit("A pasta 'static' nao foi encontrada.")

    host = resolve_server_host()
    port = resolve_server_port()
    try:
        server = ThreadingHTTPServer((host, port), PainelRequestHandler)
    except OSError as exc:
        raise SystemExit(
            f"Nao foi possivel iniciar o servidor em {host}:{port}. "
            "Verifique se o IP pertence a este notebook e se a porta esta livre."
        ) from exc

    access_urls = build_access_urls(host, port)
    print("Painel em execucao. Acesse no navegador:")
    for url in access_urls:
        print(f" - {url}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
