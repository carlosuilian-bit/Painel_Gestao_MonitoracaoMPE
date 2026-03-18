const STORAGE_KEY = "painel-gestao:analises";

const state = {
  analysis: null,
  dashboard: null,
};

const elements = {
  title: document.querySelector("#dashboard-title"),
  subtitle: document.querySelector("#dashboard-subtitle"),
  backButton: document.querySelector("#back-button"),
  refreshButton: document.querySelector("#refresh-button"),
  sources: document.querySelector("#dashboard-sources"),
  roads: document.querySelector("#dashboard-roads"),
  issues: document.querySelector("#dashboard-issues"),
  status: document.querySelector("#dashboard-status"),
  content: document.querySelector("#dashboard-content"),
  drilldownDialog: document.querySelector("#drilldown-dialog"),
  drilldownTitle: document.querySelector("#drilldown-title"),
  drilldownTotal: document.querySelector("#drilldown-total"),
  drilldownGroups: document.querySelector("#drilldown-groups"),
  closeDrilldownButton: document.querySelector("#close-drilldown-button"),
};

initialize();

function initialize() {
  elements.backButton.addEventListener("click", handleBack);
  elements.refreshButton.addEventListener("click", () => {
    void loadDashboard();
  });
  elements.closeDrilldownButton.addEventListener("click", closeDrilldown);
  elements.drilldownDialog.addEventListener("click", (event) => {
    if (event.target === elements.drilldownDialog) {
      closeDrilldown();
    }
  });

  const analysisId = new URLSearchParams(window.location.search).get("analysisId");
  if (!analysisId) {
    renderFatal("Analise nao encontrada. Volte para a lista e selecione uma configuracao valida.");
    return;
  }

  const analyses = loadAnalyses();
  const analysis = analyses.find((item) => item.id === analysisId);
  if (!analysis) {
    renderFatal("Esta analise nao existe mais no navegador. Volte para a lista e cadastre novamente.");
    return;
  }

  state.analysis = analysis;
  elements.title.textContent = analysis.databaseName || "Dashboard de monitoracao";
  elements.subtitle.textContent = "Carregando dados da analise...";
  renderSourceStrip(analysis.sources || []);
  renderTagList(elements.roads, analysis.roads || []);
  renderIssues([]);
  void loadDashboard();
}

function handleBack() {
  if (window.history.length > 1) {
    window.history.back();
    return;
  }
  window.location.href = "./index.html";
}

function loadAnalyses() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(migrateAnalysis).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function migrateAnalysis(rawAnalysis) {
  if (!rawAnalysis || typeof rawAnalysis !== "object") {
    return null;
  }

  const sources = Array.isArray(rawAnalysis.sources) && rawAnalysis.sources.length
    ? rawAnalysis.sources
    : rawAnalysis.sheetUrl
      ? [
          {
            slot: "primary",
            isPrimary: true,
            sheetUrl: rawAnalysis.sheetUrl,
            sourceKindId: "sinalizacao",
            sourceKindLabel: "Aba principal de Sinalizacao",
            displayName: rawAnalysis.databaseName || "Fonte principal",
            tabName: "Principal",
          },
        ]
      : [];

  if (!sources.length) {
    return null;
  }

  return {
    id: rawAnalysis.id || createLegacyId(rawAnalysis),
    createdAt: rawAnalysis.createdAt || new Date().toISOString(),
    databaseName: rawAnalysis.databaseName || sources[0].displayName || "Analise sem nome",
    monitoringId: rawAnalysis.monitoringId || "desconhecida",
    monitoringLabel: rawAnalysis.monitoringLabel || "Monitoracao nao identificada",
    roads: Array.isArray(rawAnalysis.roads) ? rawAnalysis.roads : [],
    sources,
  };
}

function createLegacyId(rawAnalysis) {
  const seed = [
    rawAnalysis.databaseName || "",
    rawAnalysis.sheetUrl || "",
    rawAnalysis.createdAt || "",
    Array.isArray(rawAnalysis.sources)
      ? rawAnalysis.sources.map((source) => source?.sheetUrl || "").join("|")
      : "",
  ].join("::");

  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }

  return `legacy-${hash.toString(16).padStart(8, "0")}`;
}

async function loadDashboard() {
  if (!state.analysis) {
    return;
  }

  setStatus("Montando dashboard...", "loading");
  elements.refreshButton.disabled = true;

  try {
    const payload = {
      sources: (state.analysis.sources || []).map((source) => ({
        slot: source.slot,
        isPrimary: Boolean(source.isPrimary),
        sheetUrl: source.sheetUrl,
      })),
    };

    const response = await fetch("/api/dashboard-data", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.error || "Falha ao carregar os dados do dashboard.");
    }

    state.dashboard = body;
    renderDashboard(body);
    const time = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    setStatus(`Dashboard atualizado as ${time}.`, "success");
  } catch (error) {
    elements.content.innerHTML = "";
    elements.content.append(createEmptyInline(error.message || "Falha ao montar dashboard."));
    setStatus(error.message || "Falha ao montar dashboard.", "error");
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function renderDashboard(data) {
  const monitoringLabel = data.monitoringType?.label || state.analysis?.monitoringLabel || "Monitoracao";
  const databaseName = data.databaseName || state.analysis?.databaseName || "";
  elements.title.textContent = databaseName ? `${monitoringLabel} - ${databaseName}` : monitoringLabel;
  elements.subtitle.textContent = "Clique nas setas para expandir/contrair. Clique em um resultado para ver as fichas.";

  renderSourceStrip(data.sources || state.analysis?.sources || []);
  renderTagList(elements.roads, data.roads || []);
  renderIssues(data.issues || []);

  elements.content.innerHTML = "";

  const summaryCards = Array.isArray(data.summaryCards) ? data.summaryCards : [];
  if (summaryCards.length) {
    const summary = createAccordion({
      title: "Resumo",
      meta: `${summaryCards.length} item${summaryCards.length > 1 ? "s" : ""}`,
      open: true,
      body: renderMetricList(summaryCards),
    });
    elements.content.append(summary);
  }

  const sections = Array.isArray(data.sections) ? data.sections : [];
  if (!sections.length) {
    elements.content.append(createEmptyInline("Nenhum dado foi retornado para esta analise."));
    return;
  }

  sections.forEach((section) => {
    const details = createAccordion({
      title: section.title || "Secao",
      meta: buildSectionMeta(section),
      open: false,
      body: renderSectionBody(section),
    });
    details.dataset.sectionId = section.id || "";
    elements.content.append(details);
  });
}

function renderSectionBody(section) {
  if (section.type === "list") {
    return renderMetricList(section.items || []);
  }

  if (section.type === "grouped-list") {
    return renderGroupedList(section.groups || [], section.emptyMessage);
  }

  if (section.type === "subsections") {
    return renderSubsections(section.subsections || []);
  }

  return createEmptyInline("Tipo de secao nao suportado.");
}

function renderSubsections(subsections) {
  if (!subsections.length) {
    return createEmptyInline("Nenhum subitem disponivel.");
  }

  const stack = document.createElement("div");
  stack.className = "subsection-stack";

  subsections.forEach((subsection) => {
    const details = createAccordion({
      title: subsection.title || "Subitem",
      meta: buildSectionMeta(subsection),
      open: false,
      body: renderSectionBody(subsection),
      className: "subsection-accordion",
    });
    details.dataset.subsectionId = subsection.id || "";
    stack.append(details);
  });

  return stack;
}

function renderGroupedList(groups, emptyMessage) {
  if (!groups.length) {
    return createEmptyInline(emptyMessage || "Nenhum dado disponivel.");
  }

  const stack = document.createElement("div");
  stack.className = "group-stack";

  groups.forEach((group) => {
    const items = Array.isArray(group.items) ? group.items : [];
    const total = items.reduce((sum, item) => sum + Number(item.value || 0), 0);
    const details = createAccordion({
      title: group.group || "Grupo",
      meta: `${formatNumber(total)} placa${total === 1 ? "" : "s"}`,
      open: false,
      body: renderMetricList(items),
      className: "group-accordion",
    });
    stack.append(details);
  });

  return stack;
}

function renderMetricList(items) {
  if (!items.length) {
    return createEmptyInline("Nenhum registro encontrado.");
  }

  const list = document.createElement("div");
  list.className = "metric-column";
  items.forEach((item) => list.append(createMetricRow(item)));
  return list;
}

function createMetricRow(item) {
  const hasDrilldown = Boolean(item.drilldownKey);
  const row = document.createElement(hasDrilldown ? "button" : "div");
  row.className = hasDrilldown ? "metric-row metric-row--button" : "metric-row";
  if (hasDrilldown) {
    row.type = "button";
    row.addEventListener("click", () => openDrilldown(item.drilldownKey, item.label));
  }

  const labelWrap = document.createElement("div");
  labelWrap.className = "metric-row__label";

  const strong = document.createElement("strong");
  strong.textContent = item.label || "Sem rotulo";
  labelWrap.append(strong);

  const details = Array.isArray(item.details) ? item.details.filter(Boolean) : [];
  details.forEach((detail) => {
    const detailNode = document.createElement("span");
    detailNode.className = "metric-row__detail";
    detailNode.textContent = detail;
    labelWrap.append(detailNode);
  });

  const value = document.createElement("span");
  value.className = "metric-row__value";
  value.textContent = item.valueFormatted || formatNumber(item.value || 0);

  row.append(labelWrap, value);
  return row;
}

function createAccordion({ title, meta, body, open, className = "" }) {
  const details = document.createElement("details");
  details.className = `accordion-item ${className}`.trim();
  details.open = Boolean(open);

  const summary = document.createElement("summary");
  summary.className = "accordion-summary";

  const heading = document.createElement("div");
  heading.className = "accordion-heading";
  const headingTitle = document.createElement("h3");
  headingTitle.textContent = title || "Secao";
  heading.append(headingTitle);

  const metaNode = document.createElement("span");
  metaNode.className = "accordion-meta";
  metaNode.textContent = meta || "";

  summary.append(heading, metaNode);

  const wrapper = document.createElement("div");
  wrapper.className = "accordion-body";
  wrapper.append(body);

  details.append(summary, wrapper);
  return details;
}

function buildSectionMeta(section) {
  if (section.type === "list") {
    const count = Array.isArray(section.items) ? section.items.length : 0;
    return `${count} item${count === 1 ? "" : "s"}`;
  }

  if (section.type === "subsections") {
    const count = Array.isArray(section.subsections) ? section.subsections.length : 0;
    return `${count} subitem${count === 1 ? "" : "s"}`;
  }

  if (section.type === "grouped-list") {
    const count = Array.isArray(section.groups) ? section.groups.length : 0;
    return `${count} grupo${count === 1 ? "" : "s"}`;
  }

  return "";
}

function openDrilldown(drilldownKey, fallbackTitle) {
  const drilldown = state.dashboard?.drilldowns?.[drilldownKey];
  if (!drilldown) {
    elements.drilldownTitle.textContent = fallbackTitle || "Detalhamento";
    elements.drilldownTotal.textContent = "Nenhum item disponivel para detalhamento.";
    elements.drilldownGroups.innerHTML = "";
    elements.drilldownGroups.append(createEmptyInline("Sem fichas para exibir."));
    elements.drilldownDialog.showModal();
    return;
  }

  elements.drilldownTitle.textContent = drilldown.title || fallbackTitle || "Detalhamento";
  elements.drilldownTotal.textContent = `Total: ${formatNumber(drilldown.total || 0)}`;

  elements.drilldownGroups.innerHTML = "";
  const groups = Array.isArray(drilldown.groups) ? drilldown.groups : [];
  if (!groups.length) {
    elements.drilldownGroups.append(createEmptyInline("Sem fichas para exibir."));
  } else {
    groups.forEach((group) => {
      const block = document.createElement("section");
      block.className = "drilldown-group";

      const title = document.createElement("h4");
      title.textContent = group.uf || "Sem UF";

      const list = document.createElement("ul");
      list.className = "drilldown-list";
      (group.items || []).forEach((item) => {
        const line = document.createElement("li");
        line.textContent = item;
        list.append(line);
      });

      block.append(title, list);
      elements.drilldownGroups.append(block);
    });
  }

  elements.drilldownDialog.showModal();
}

function closeDrilldown() {
  if (elements.drilldownDialog.open) {
    elements.drilldownDialog.close();
  }
}

function renderSourceStrip(sources) {
  elements.sources.innerHTML = "";
  if (!sources.length) {
    return;
  }

  sources.forEach((source) => {
    const tabName = source.tabName || source.slot || "Fonte";
    const typeLabel = source.sourceKind?.label || source.sourceKindLabel || "";
    const label = typeLabel ? `${tabName} - ${typeLabel}` : tabName;
    elements.sources.append(createSourcePill(label));
  });
}

function renderIssues(issues) {
  elements.issues.innerHTML = "";
  if (!issues.length) {
    elements.issues.hidden = true;
    return;
  }

  elements.issues.hidden = false;
  issues.forEach((issue) => {
    const banner = document.createElement("div");
    banner.className = "issue-banner";
    banner.textContent = issue;
    elements.issues.append(banner);
  });
}

function renderTagList(container, values) {
  container.innerHTML = "";
  values.forEach((value) => container.append(createTag(value)));
}

function createSourcePill(label) {
  const pill = document.createElement("span");
  pill.className = "source-pill";
  pill.textContent = label;
  return pill;
}

function createTag(label) {
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = label;
  return tag;
}

function createEmptyInline(text) {
  const box = document.createElement("div");
  box.className = "empty-inline";
  const strong = document.createElement("strong");
  strong.textContent = text;
  box.append(strong);
  return box;
}

function setStatus(message, tone = "") {
  elements.status.className = "status";
  if (tone) {
    elements.status.classList.add(`is-${tone}`);
  }
  elements.status.textContent = message;
}

function renderFatal(message) {
  elements.title.textContent = "Dashboard indisponivel";
  elements.subtitle.textContent = message;
  elements.content.innerHTML = "";
  elements.content.append(createEmptyInline(message));
  setStatus(message, "error");
  elements.refreshButton.disabled = true;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("pt-BR");
}
