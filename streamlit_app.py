from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
import urllib.error
import uuid

import streamlit as st

from server import build_dashboard, build_source_preview, clean_cell


SOURCE_SLOTS = (
    {
        "slot": "primary",
        "label": "Link Principal",
        "placeholder": "Cole o link principal da analise",
        "help": "Essa fonte define o tipo de monitoracao e a base principal da analise.",
        "required": True,
    },
    {
        "slot": "additional-1",
        "label": "Link Adicional 1",
        "placeholder": "Cole um link adicional",
        "help": "Use para vincular a aba de Medicao ou outra planilha complementar.",
        "required": False,
    },
    {
        "slot": "additional-2",
        "label": "Link Adicional 2",
        "placeholder": "Cole um segundo link adicional",
        "help": "Opcional. Pode ser usado para uma segunda fonte complementar.",
        "required": False,
    },
)


def input_key(slot_name: str) -> str:
    return f"source_url::{slot_name}"


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
          padding-top: 2rem;
          padding-bottom: 2.5rem;
        }
        .pg-badge-wrap {
          display: flex;
          flex-wrap: wrap;
          gap: 0.4rem;
          margin: 0.35rem 0 0.2rem;
        }
        .pg-badge {
          display: inline-block;
          padding: 0.18rem 0.7rem;
          border-radius: 999px;
          border: 1px solid #b8cdbd;
          background: #eef6f0;
          color: #173221;
          font-size: 0.82rem;
          line-height: 1.3;
        }
        .pg-count {
          text-align: right;
          font-weight: 700;
          padding-top: 0.35rem;
        }
        .pg-meta {
          color: #4f5b56;
          font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_state() -> None:
    defaults = {
        "analyses": [],
        "dashboard_cache": {},
        "selected_analysis_id": None,
        "selected_drilldown_key": None,
        "draft_previews": {},
        "draft_errors": {},
        "flash": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    for slot in SOURCE_SLOTS:
        key = input_key(slot["slot"])
        if key not in st.session_state:
            st.session_state[key] = ""


def render_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if not flash:
        return

    tone = flash.get("tone")
    message = flash.get("message", "")
    if tone == "success":
        st.success(message)
    elif tone == "warning":
        st.warning(message)
    else:
        st.error(message)


def format_timestamp(value: str) -> str:
    if not value:
        return "Data nao informada"

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value

    return parsed.astimezone().strftime("%d/%m/%Y %H:%M")


def render_badges(values: list[str], empty_label: str, container: object | None = None) -> None:
    target = container if container is not None else st
    safe_values = [clean_cell(value) for value in values if clean_cell(value)]
    if not safe_values:
        target.caption(empty_label)
        return

    badges = "".join(f"<span class='pg-badge'>{escape(value)}</span>" for value in safe_values)
    target.markdown(f"<div class='pg-badge-wrap'>{badges}</div>", unsafe_allow_html=True)


def collect_source_urls() -> dict[str, str]:
    return {slot["slot"]: clean_cell(str(st.session_state.get(input_key(slot["slot"]), ""))) for slot in SOURCE_SLOTS}


def validate_urls(urls_by_slot: dict[str, str]) -> str | None:
    primary_url = urls_by_slot.get("primary", "")
    if not primary_url:
        return "Informe o Link Principal antes de validar a analise."

    filled_urls = [url for url in urls_by_slot.values() if url]
    if len(set(filled_urls)) != len(filled_urls):
        return "Os links nao podem ser repetidos entre as fontes da mesma analise."

    return None


def describe_exception(exc: Exception, fallback_message: str) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == HTTPStatus.NOT_FOUND:
            return "A planilha nao foi encontrada."
        if exc.code in {HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED}:
            return "A planilha nao esta acessivel para leitura."
        return "Falha ao consultar a planilha informada."
    if isinstance(exc, urllib.error.URLError):
        return "Nao foi possivel acessar a planilha. Verifique a conexao e tente novamente."
    return fallback_message


def analyze_sources(urls_by_slot: dict[str, str]) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    previews: dict[str, dict[str, object]] = {}
    errors: dict[str, str] = {}

    for slot in SOURCE_SLOTS:
        slot_name = slot["slot"]
        sheet_url = urls_by_slot.get(slot_name, "")
        if not sheet_url:
            continue

        try:
            preview = build_source_preview(sheet_url)
            preview["slot"] = slot_name
            preview["isPrimary"] = slot_name == "primary"
            previews[slot_name] = preview
        except Exception as exc:  # noqa: BLE001
            errors[slot_name] = describe_exception(exc, "Ocorreu um erro interno ao analisar a planilha.")

    return previews, errors


def validate_previews(
    urls_by_slot: dict[str, str],
    previews: dict[str, dict[str, object]],
    errors: dict[str, str],
) -> tuple[bool, str, str]:
    error_message = validate_urls(urls_by_slot)
    if error_message:
        return False, error_message, "error"

    if errors:
        first_error = next(iter(errors.values()))
        return False, first_error, "error"

    primary_preview = previews.get("primary")
    if not primary_preview:
        return False, "Nao foi possivel validar o Link Principal.", "error"

    if primary_preview["monitoringType"]["id"] == "desconhecida":
        return False, "O Link Principal precisa identificar uma monitoracao valida.", "error"

    missing_slots = [slot["label"] for slot in SOURCE_SLOTS if urls_by_slot.get(slot["slot"]) and slot["slot"] not in previews]
    if missing_slots:
        return False, f"Confirme todas as fontes preenchidas antes de salvar. Pendente: {missing_slots[0]}.", "error"

    if primary_preview["monitoringType"]["id"] == "sinalizacao_vertical":
        has_measurement = any(
            preview["sourceKind"]["id"] == "medicao"
            for slot_name, preview in previews.items()
            if slot_name != "primary"
        )
        if not has_measurement:
            return False, "Para Sinalizacao Vertical, adicione tambem uma fonte do tipo Medicao.", "error"

    return True, "Todas as fontes foram confirmadas. Voce ja pode salvar a analise.", "success"


def build_analysis_record(
    urls_by_slot: dict[str, str],
    previews: dict[str, dict[str, object]],
) -> dict[str, object]:
    primary_preview = previews["primary"]
    sources = []
    for slot in SOURCE_SLOTS:
        slot_name = slot["slot"]
        preview = previews.get(slot_name)
        sheet_url = urls_by_slot.get(slot_name, "")
        if not preview or not sheet_url:
            continue

        sources.append(
            {
                "slot": slot_name,
                "isPrimary": slot_name == "primary",
                "sheetUrl": sheet_url,
                "displayName": preview["displayName"],
                "tabName": preview["tabName"],
                "sourceKindId": preview["sourceKind"]["id"],
                "sourceKindLabel": preview["sourceKind"]["label"],
                "rowCount": preview["rowCount"],
            }
        )

    return {
        "id": uuid.uuid4().hex,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "databaseName": primary_preview["databaseName"],
        "monitoringId": primary_preview["monitoringType"]["id"],
        "monitoringLabel": primary_preview["monitoringType"]["label"],
        "roads": primary_preview["roads"],
        "sources": sources,
    }


def clear_draft() -> None:
    st.session_state["draft_previews"] = {}
    st.session_state["draft_errors"] = {}
    for slot in SOURCE_SLOTS:
        st.session_state[input_key(slot["slot"])] = ""


def get_selected_analysis() -> dict[str, object] | None:
    analysis_id = st.session_state.get("selected_analysis_id")
    if not analysis_id:
        return None
    return next((analysis for analysis in st.session_state["analyses"] if analysis["id"] == analysis_id), None)


def load_dashboard_record(analysis: dict[str, object], force_refresh: bool = False) -> dict[str, object]:
    analysis_id = str(analysis["id"])
    cache = st.session_state["dashboard_cache"]
    if not force_refresh and analysis_id in cache:
        return cache[analysis_id]

    payload = {
        "sources": [
            {
                "slot": source.get("slot", ""),
                "isPrimary": bool(source.get("isPrimary")),
                "sheetUrl": source.get("sheetUrl", ""),
            }
            for source in analysis.get("sources", [])
        ]
    }

    try:
        with st.spinner("Montando dashboard..."):
            data = build_dashboard(payload)
        cache[analysis_id] = {
            "data": data,
            "error": None,
            "loadedAt": datetime.now().strftime("%H:%M"),
        }
    except Exception as exc:  # noqa: BLE001
        cache[analysis_id] = {
            "data": None,
            "error": describe_exception(exc, "Ocorreu um erro interno ao montar o dashboard."),
            "loadedAt": None,
        }

    return cache[analysis_id]


def build_section_meta(section: dict[str, object]) -> str:
    section_type = section.get("type")
    if section_type == "list":
        items = section.get("items", [])
        count = len(items) if isinstance(items, list) else 0
        return f"{count} item" if count == 1 else f"{count} itens"
    if section_type == "grouped-list":
        groups = section.get("groups", [])
        count = len(groups) if isinstance(groups, list) else 0
        return f"{count} grupo" if count == 1 else f"{count} grupos"
    if section_type == "subsections":
        subsections = section.get("subsections", [])
        count = len(subsections) if isinstance(subsections, list) else 0
        return f"{count} subitem" if count == 1 else f"{count} subitens"
    return ""


def render_metric_list(items: list[dict[str, object]], key_prefix: str) -> None:
    if not items:
        st.info("Nenhum registro encontrado.")
        return

    for index, item in enumerate(items):
        row = st.container()
        label_col, value_col, action_col = row.columns([6, 1.4, 1.2])

        label_col.markdown(f"**{item.get('label', 'Sem rotulo')}**")
        for detail in item.get("details", []):
            if detail:
                label_col.caption(str(detail))

        value = item.get("valueFormatted") or str(item.get("value", 0))
        value_col.markdown(f"<div class='pg-count'>{escape(str(value))}</div>", unsafe_allow_html=True)

        drilldown_key = item.get("drilldownKey")
        if drilldown_key and action_col.button("Fichas", key=f"{key_prefix}::{index}::{drilldown_key}", use_container_width=True):
            st.session_state["selected_drilldown_key"] = drilldown_key

        if index < len(items) - 1:
            st.divider()


def render_grouped_list(groups: list[dict[str, object]], empty_message: str | None, key_prefix: str) -> None:
    if not groups:
        st.info(empty_message or "Nenhum dado disponivel.")
        return

    for index, group in enumerate(groups):
        group_items = group.get("items", [])
        total = sum(int(item.get("value", 0)) for item in group_items if isinstance(item, dict))
        with st.container(border=True):
            st.markdown(f"**{group.get('group', 'Grupo')}**")
            st.caption(f"{total} placa" if total == 1 else f"{total} placas")
            render_metric_list(group_items, f"{key_prefix}::group::{index}")


def render_subsections(subsections: list[dict[str, object]], key_prefix: str) -> None:
    if not subsections:
        st.info("Nenhum subitem disponivel.")
        return

    for index, subsection in enumerate(subsections):
        if index:
            st.divider()
        st.markdown(f"#### {subsection.get('title', 'Subitem')}")
        render_section_body(subsection, f"{key_prefix}::sub::{index}")


def render_section_body(section: dict[str, object], key_prefix: str) -> None:
    section_type = section.get("type")
    if section_type == "list":
        render_metric_list(section.get("items", []), key_prefix)
        return
    if section_type == "grouped-list":
        render_grouped_list(section.get("groups", []), section.get("emptyMessage"), key_prefix)
        return
    if section_type == "subsections":
        render_subsections(section.get("subsections", []), key_prefix)
        return
    st.info("Tipo de secao nao suportado.")


def render_drilldown(data: dict[str, object]) -> None:
    selected_drilldown_key = st.session_state.get("selected_drilldown_key")
    if not selected_drilldown_key:
        return

    drilldowns = data.get("drilldowns", {})
    drilldown = drilldowns.get(selected_drilldown_key)
    if not drilldown:
        st.session_state["selected_drilldown_key"] = None
        return

    st.markdown("### Detalhamento")
    top_col, close_col = st.columns([5, 1])
    top_col.markdown(f"**{drilldown.get('title', 'Detalhamento')}**")
    top_col.caption(f"Total: {drilldown.get('total', 0)}")
    if close_col.button("Fechar", key=f"close::{selected_drilldown_key}", use_container_width=True):
        st.session_state["selected_drilldown_key"] = None
        st.rerun()

    groups = drilldown.get("groups", [])
    if not groups:
        st.info("Sem fichas para exibir.")
        return

    for group in groups:
        with st.container(border=True):
            st.markdown(f"**{group.get('uf', 'Sem UF')}**")
            for item in group.get("items", []):
                st.write(str(item))


def render_source_preview_blocks() -> None:
    previews = st.session_state.get("draft_previews", {})
    errors = st.session_state.get("draft_errors", {})
    if not previews and not errors:
        return

    st.markdown("#### Resultado da validacao")
    for slot in SOURCE_SLOTS:
        slot_name = slot["slot"]
        preview = previews.get(slot_name)
        error_message = errors.get(slot_name)
        if not preview and not error_message:
            continue

        with st.container(border=True):
            st.markdown(f"**{slot['label']}**")
            if error_message:
                st.error(error_message)
                continue

            top_left, top_right = st.columns(2)
            top_left.caption("Banco identificado")
            top_left.write(str(preview.get("databaseName", "-")))
            top_right.caption("Aba detectada")
            top_right.write(str(preview.get("tabName", "-")))

            middle_left, middle_right = st.columns(2)
            middle_left.caption("Tipo da fonte")
            middle_left.write(str(preview["sourceKind"]["label"]))
            middle_right.caption("Monitoracao")
            middle_right.write(str(preview["monitoringType"]["label"]))

            bottom_left, bottom_right = st.columns(2)
            bottom_left.caption("Rodovias")
            render_badges(preview.get("roads", []), "Sem rodovias", bottom_left)
            bottom_right.caption("Registros validos")
            bottom_right.write(str(preview.get("rowCount", 0)))


def render_analysis_form() -> None:
    st.subheader("Cadastrar monitoracao")
    st.caption("Para Sinalizacao Vertical, informe o Link Principal e pelo menos uma fonte do tipo Medicao.")

    feedback: tuple[str, str] | None = None

    with st.form("analysis-form", clear_on_submit=False):
        for slot in SOURCE_SLOTS:
            st.text_input(
                slot["label"],
                key=input_key(slot["slot"]),
                placeholder=slot["placeholder"],
                help=slot["help"],
            )

        button_col, save_col = st.columns(2)
        validate_clicked = button_col.form_submit_button("Validar fontes", use_container_width=True)
        save_clicked = save_col.form_submit_button("Salvar analise", type="primary", use_container_width=True)

    if validate_clicked or save_clicked:
        urls_by_slot = collect_source_urls()
        error_message = validate_urls(urls_by_slot)
        if error_message:
            st.session_state["draft_previews"] = {}
            st.session_state["draft_errors"] = {}
            feedback = ("error", error_message)
        else:
            with st.spinner("Analisando fontes..."):
                previews, errors = analyze_sources(urls_by_slot)

            st.session_state["draft_previews"] = previews
            st.session_state["draft_errors"] = errors
            can_save, message, tone = validate_previews(urls_by_slot, previews, errors)
            feedback = (tone, message)

            if save_clicked and can_save:
                analysis = build_analysis_record(urls_by_slot, previews)
                st.session_state["analyses"].insert(0, analysis)
                st.session_state["selected_analysis_id"] = analysis["id"]
                st.session_state["selected_drilldown_key"] = None
                clear_draft()
                st.session_state["flash"] = {
                    "tone": "success",
                    "message": "Analise salva e pronta para abrir no dashboard.",
                }
                st.rerun()

    if feedback:
        tone, message = feedback
        if tone == "success":
            st.success(message)
        else:
            st.error(message)

    render_source_preview_blocks()


def render_analyses_list() -> None:
    st.subheader("Analises cadastradas")
    analyses = st.session_state["analyses"]
    if not analyses:
        st.info("Nenhuma analise cadastrada nesta sessao.")
        return

    for analysis in analyses:
        with st.container(border=True):
            info_col, open_col, delete_col = st.columns([6, 1.2, 1.2])
            info_col.markdown(f"**{analysis.get('databaseName', 'Analise sem nome')}**")
            info_col.caption(f"{analysis.get('monitoringLabel', 'Monitoracao')} | {format_timestamp(str(analysis.get('createdAt', '')))}")
            render_badges(analysis.get("roads", []), "Sem rodovias", info_col)
            source_labels = [
                f"{source.get('tabName', source.get('slot', 'Fonte'))} - {source.get('sourceKindLabel', 'Fonte')}"
                for source in analysis.get("sources", [])
            ]
            info_col.caption("Fontes")
            render_badges(source_labels, "Sem fontes", info_col)

            if open_col.button("Abrir", key=f"open::{analysis['id']}", use_container_width=True):
                st.session_state["selected_analysis_id"] = analysis["id"]
                st.session_state["selected_drilldown_key"] = None

            if delete_col.button("Excluir", key=f"delete::{analysis['id']}", use_container_width=True):
                st.session_state["analyses"] = [item for item in analyses if item["id"] != analysis["id"]]
                st.session_state["dashboard_cache"].pop(str(analysis["id"]), None)
                if st.session_state.get("selected_analysis_id") == analysis["id"]:
                    st.session_state["selected_analysis_id"] = None
                    st.session_state["selected_drilldown_key"] = None
                st.session_state["flash"] = {
                    "tone": "success",
                    "message": "Analise removida da sessao atual.",
                }
                st.rerun()


def render_summary_cards(summary_cards: list[dict[str, object]], key_prefix: str) -> None:
    if not summary_cards:
        return

    columns = st.columns(len(summary_cards))
    for index, item in enumerate(summary_cards):
        with columns[index]:
            st.metric(str(item.get("label", "Resumo")), str(item.get("valueFormatted", item.get("value", 0))))
            drilldown_key = item.get("drilldownKey")
            if drilldown_key and st.button("Ver fichas", key=f"{key_prefix}::summary::{index}", use_container_width=True):
                st.session_state["selected_drilldown_key"] = drilldown_key


def render_dashboard_panel() -> None:
    st.subheader("Dashboard")
    analysis = get_selected_analysis()
    if not analysis:
        st.info("Selecione uma analise cadastrada para abrir o dashboard.")
        return

    title_col, action_col = st.columns([5, 1])
    title_col.markdown(f"**{analysis.get('databaseName', 'Dashboard de monitoracao')}**")
    title_col.caption(analysis.get("monitoringLabel", "Monitoracao"))
    refresh_clicked = action_col.button("Atualizar", key=f"refresh::{analysis['id']}", use_container_width=True)

    dashboard_record = load_dashboard_record(analysis, force_refresh=refresh_clicked)
    if dashboard_record.get("error"):
        st.error(str(dashboard_record["error"]))
        return

    data = dashboard_record.get("data")
    if not data:
        st.info("Nenhum dado foi retornado para esta analise.")
        return

    st.caption(f"Ultima atualizacao: {dashboard_record.get('loadedAt', '--:--')}")

    source_labels = [
        f"{source.get('tabName', source.get('slot', 'Fonte'))} - {source.get('sourceKind', {}).get('label', source.get('sourceKindLabel', 'Fonte'))}"
        for source in data.get("sources", [])
    ]
    st.caption("Fontes vinculadas")
    render_badges(source_labels, "Sem fontes")

    st.caption("Rodovias")
    render_badges(data.get("roads", []), "Sem rodovias")

    for issue in data.get("issues", []):
        st.warning(str(issue))

    render_summary_cards(data.get("summaryCards", []), f"dashboard::{analysis['id']}")

    for index, section in enumerate(data.get("sections", [])):
        section_title = str(section.get("title", "Secao"))
        meta = build_section_meta(section)
        expander_title = f"{section_title} ({meta})" if meta else section_title
        with st.expander(expander_title, expanded=False):
            render_section_body(section, f"dashboard::{analysis['id']}::section::{index}")

    render_drilldown(data)


def main() -> None:
    st.set_page_config(page_title="Painel de Gestao", layout="wide")
    inject_styles()
    initialize_state()

    st.title("Painel de Gestao")
    st.caption("Cadastro e leitura de analises de monitoracao com dashboard consolidado para Sinalizacao Vertical.")
    st.info("As analises ficam salvas na sessao atual do navegador. Para compartilhar, publique este repositorio no GitHub e abra pelo Streamlit Community Cloud.")
    render_flash()

    left_col, right_col = st.columns([1, 1.2], gap="large")

    with left_col:
        render_analysis_form()
        st.divider()
        render_analyses_list()

    with right_col:
        render_dashboard_panel()


if __name__ == "__main__":
    main()
