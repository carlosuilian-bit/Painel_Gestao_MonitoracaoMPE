const STORAGE_KEY = "painel-gestao:analises";
const AUTO_READ_DELAY_MS = 700;
const MAX_ADDITIONAL_SOURCES = 2;

const SOURCE_SLOTS = [
  {
    slot: "primary",
    defaultMessage: "Informe o link principal para iniciar a identificacao automatica.",
    emptyMessage: "Informe o link principal para iniciar a identificacao automatica.",
    isPrimary: true,
    visible: true,
  },
  {
    slot: "additional-1",
    defaultMessage: "Cole um link adicional para identificar a fonte.",
    emptyMessage: "Cole um link adicional para identificar a fonte.",
    isPrimary: false,
    visible: false,
  },
  {
    slot: "additional-2",
    defaultMessage: "Cole um link adicional para identificar a fonte.",
    emptyMessage: "Cole um link adicional para identificar a fonte.",
    isPrimary: false,
    visible: false,
  },
];

const state = {
  analyses: loadAnalyses(),
  sourceSlots: createSlotState(),
  slotTimers: {},
  deleteSelection: new Set(),
};

const elements = {
  analysisCounter: document.querySelector("#analysis-counter"),
  analysisList: document.querySelector("#analysis-list"),
  addButton: document.querySelector("#add-analysis-button"),
  deleteButton: document.querySelector("#delete-analysis-button"),
  analysisDialog: document.querySelector("#analysis-dialog"),
  analysisForm: document.querySelector("#analysis-form"),
  closeDialogButton: document.querySelector("#close-dialog-button"),
  cancelDialogButton: document.querySelector("#cancel-dialog-button"),
  confirmAnalysisButton: document.querySelector("#confirm-analysis-button"),
  addSourceButton: document.querySelector("#add-source-button"),
  formStatus: document.querySelector("#form-status"),
  deleteDialog: document.querySelector("#delete-dialog"),
  deleteForm: document.querySelector("#delete-form"),
  deleteList: document.querySelector("#delete-list"),
  closeDeleteDialogButton: document.querySelector("#close-delete-dialog-button"),
  cancelDeleteButton: document.querySelector("#cancel-delete-button"),
  confirmDeleteButton: document.querySelector("#confirm-delete-button"),
  analysisTemplate: document.querySelector("#analysis-item-template"),
};

const slotElements = mapSlotElements();

initialize();

function initialize() {
  elements.addButton.addEventListener("click", openAnalysisDialog);
  elements.deleteButton.addEventListener("click", openDeleteDialog);
  elements.closeDialogButton.addEventListener("click", closeAnalysisDialog);
  elements.cancelDialogButton.addEventListener("click", closeAnalysisDialog);
  elements.analysisDialog.addEventListener("close", clearAllSlotTimers);
  elements.analysisDialog.addEventListener("click", (event) => {
    if (event.target === elements.analysisDialog) {
      closeAnalysisDialog();
    }
  });
  elements.analysisForm.addEventListener("submit", confirmAnalysis);
  elements.addSourceButton.addEventListener("click", showNextAdditionalSlot);

  elements.closeDeleteDialogButton.addEventListener("click", closeDeleteDialog);
  elements.cancelDeleteButton.addEventListener("click", closeDeleteDialog);
  elements.deleteDialog.addEventListener("click", (event) => {
    if (event.target === elements.deleteDialog) {
      closeDeleteDialog();
    }
  });
  elements.deleteForm.addEventListener("submit", confirmDeleteSelection);

  for (const slot of SOURCE_SLOTS) {
    const input = slotElements[slot.slot].input;
    input.addEventListener("input", (event) => handleSourceInput(slot.slot, event.target.value));
    if (!slot.isPrimary) {
      slotElements[slot.slot].removeButton.addEventListener("click", () => hideAdditionalSlot(slot.slot));
    }
  }

  renderSourceSlots();
  renderAnalysisList();
}

function createSlotState() {
  return SOURCE_SLOTS.map((slot) => ({
    ...slot,
    value: "",
    preview: null,
    loading: false,
    tone: "",
    message: slot.defaultMessage,
    requestToken: 0,
  }));
}

function mapSlotElements() {
  const mapping = {};
  for (const slot of SOURCE_SLOTS) {
    mapping[slot.slot] = {
      container: document.querySelector(`[data-slot="${slot.slot}"]`),
      input: document.querySelector(`[data-slot-input="${slot.slot}"]`),
      status: document.querySelector(`[data-slot-status="${slot.slot}"]`),
      preview: document.querySelector(`[data-slot-preview="${slot.slot}"]`),
      database: document.querySelector(`[data-slot-database="${slot.slot}"]`),
      tab: document.querySelector(`[data-slot-tab="${slot.slot}"]`),
      kind: document.querySelector(`[data-slot-kind="${slot.slot}"]`),
      monitoring: document.querySelector(`[data-slot-monitoring="${slot.slot}"]`),
      roads: document.querySelector(`[data-slot-roads="${slot.slot}"]`),
      rows: document.querySelector(`[data-slot-rows="${slot.slot}"]`),
      removeButton: document.querySelector(`[data-slot-remove="${slot.slot}"]`),
    };
  }
  return mapping;
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

function saveAnalyses() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.analyses));
}

function renderAnalysisList() {
  const total = state.analyses.length;
  elements.analysisCounter.textContent = `${total} ${total === 1 ? "analise" : "analises"}`;
  elements.analysisList.innerHTML = "";
  elements.deleteButton.disabled = !total;

  if (!total) {
    const emptyState = document.createElement("div");
    emptyState.className = "empty-state";
    emptyState.innerHTML =
      "<div><strong>Nenhuma analise cadastrada.</strong><p>Use o botao abaixo para adicionar a primeira monitoracao.</p></div>";
    elements.analysisList.append(emptyState);
    return;
  }

  for (const analysis of state.analyses) {
    const fragment = elements.analysisTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".analysis-card");
    const type = fragment.querySelector(".analysis-type");
    const date = fragment.querySelector(".analysis-date");
    const name = fragment.querySelector(".analysis-name");
    const link = fragment.querySelector(".analysis-link");
    const roads = fragment.querySelector(".analysis-roads");
    const sources = fragment.querySelector(".analysis-sources");

    const openDashboard = () => {
      window.location.href = `./dashboard.html?analysisId=${encodeURIComponent(analysis.id)}`;
    };
    card.addEventListener("click", openDashboard);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDashboard();
      }
    });

    type.textContent = analysis.monitoringLabel;
    date.textContent = formatDate(analysis.createdAt);
    name.textContent = analysis.databaseName;
    link.textContent = analysis.sources.map((source) => source.displayName || source.sheetUrl).join(" | ");

    (analysis.roads || []).forEach((road) => roads.append(createTag(road)));
    analysis.sources.forEach((source) => sources.append(createSourcePill(source.tabName || source.sourceKindLabel || source.slot)));
    elements.analysisList.append(fragment);
  }
}

function openAnalysisDialog() {
  resetAnalysisDialog();
  elements.analysisDialog.showModal();
  slotElements.primary.input.focus();
}

function closeAnalysisDialog() {
  elements.analysisDialog.close();
}

function resetAnalysisDialog() {
  clearAllSlotTimers();
  state.sourceSlots = createSlotState();
  renderSourceSlots();
  updateFormState();
}

function renderSourceSlots() {
  for (const slotState of state.sourceSlots) {
    const ui = slotElements[slotState.slot];
    ui.container.hidden = !slotState.visible;
    ui.input.value = slotState.value;
    setStatusElement(ui.status, slotState.message, slotState.tone, slotState.loading);
    renderSlotPreview(slotState.slot);
  }

  const visibleAdditionals = getVisibleAdditionalSlots();
  elements.addSourceButton.disabled = visibleAdditionals.length >= MAX_ADDITIONAL_SOURCES;
  elements.addSourceButton.hidden = visibleAdditionals.length >= MAX_ADDITIONAL_SOURCES;
}

function renderSlotPreview(slotName) {
  const slotState = getSlotState(slotName);
  const ui = slotElements[slotName];

  if (!slotState.preview) {
    ui.preview.hidden = true;
    renderTagList(ui.roads, []);
    return;
  }

  ui.preview.hidden = false;
  ui.database.textContent = slotState.preview.databaseName;
  ui.tab.textContent = slotState.preview.tabName;
  ui.kind.textContent = slotState.preview.sourceKind.label;
  ui.monitoring.textContent = slotState.preview.monitoringType.label;
  ui.rows.textContent = formatNumber(slotState.preview.rowCount);
  renderTagList(ui.roads, slotState.preview.roads.length ? slotState.preview.roads : ["Sem rodovias"]);
}

function showNextAdditionalSlot() {
  const nextSlot = state.sourceSlots.find((slot) => !slot.isPrimary && !slot.visible);
  if (!nextSlot) {
    return;
  }

  nextSlot.visible = true;
  nextSlot.message = nextSlot.defaultMessage;
  nextSlot.tone = "";
  nextSlot.preview = null;
  nextSlot.loading = false;
  renderSourceSlots();
  updateFormState();
  slotElements[nextSlot.slot].input.focus();
}

function hideAdditionalSlot(slotName) {
  const slotState = getSlotState(slotName);
  if (!slotState || slotState.isPrimary) {
    return;
  }

  clearSlotTimer(slotName);
  Object.assign(slotState, {
    visible: false,
    value: "",
    preview: null,
    loading: false,
    tone: "",
    message: slotState.defaultMessage,
    requestToken: slotState.requestToken + 1,
  });
  renderSourceSlots();
  updateFormState();
}

function handleSourceInput(slotName, value) {
  const slotState = getSlotState(slotName);
  slotState.value = value.trim();
  slotState.preview = null;
  slotState.loading = false;
  slotState.requestToken += 1;
  clearSlotTimer(slotName);

  if (!slotState.value) {
    slotState.message = slotState.emptyMessage;
    slotState.tone = "";
    renderSlotPreview(slotName);
    setStatusElement(slotElements[slotName].status, slotState.message, slotState.tone, false);
    updateFormState();
    return;
  }

  slotState.loading = true;
  slotState.message = "Lendo a fonte e identificando a estrutura...";
  slotState.tone = "loading";
  setStatusElement(slotElements[slotName].status, slotState.message, slotState.tone, true);
  slotElements[slotName].preview.hidden = true;
  state.slotTimers[slotName] = window.setTimeout(() => fetchSourcePreview(slotName), AUTO_READ_DELAY_MS);
  updateFormState();
}

async function fetchSourcePreview(slotName) {
  const slotState = getSlotState(slotName);
  const requestToken = slotState.requestToken;

  try {
    const response = await fetch("/api/analyze-sheet", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url: slotState.value }),
    });

    const payload = await response.json();
    if (getSlotState(slotName).requestToken !== requestToken) {
      return;
    }

    if (!response.ok) {
      throw new Error(payload.error || "Falha ao analisar a fonte.");
    }

    slotState.preview = payload;
    slotState.loading = false;
    slotState.tone = payload.sourceKind.id === "desconhecida" ? "error" : "success";
    slotState.message =
      payload.sourceKind.id === "desconhecida"
        ? "A fonte foi lida, mas o tipo dela nao foi identificado."
        : "Fonte identificada. Revise os dados abaixo.";

    renderSlotPreview(slotName);
    setStatusElement(slotElements[slotName].status, slotState.message, slotState.tone, false);
  } catch (error) {
    if (getSlotState(slotName).requestToken !== requestToken) {
      return;
    }

    slotState.preview = null;
    slotState.loading = false;
    slotState.tone = "error";
    slotState.message = error.message;
    slotElements[slotName].preview.hidden = true;
    setStatusElement(slotElements[slotName].status, slotState.message, slotState.tone, false);
  }

  updateFormState();
}

function updateFormState() {
  const validation = validateAnalysisForm();
  elements.confirmAnalysisButton.disabled = !validation.canConfirm;
  setStatusElement(elements.formStatus, validation.message, validation.tone, false);
}

function validateAnalysisForm() {
  const visibleSlots = state.sourceSlots.filter((slot) => slot.visible);
  const filledUrls = visibleSlots.filter((slot) => slot.value).map((slot) => slot.value);

  if (new Set(filledUrls).size !== filledUrls.length) {
    return {
      canConfirm: false,
      message: "Os links nao podem ser repetidos entre as fontes da mesma analise.",
      tone: "error",
    };
  }

  const emptyVisibleAdditional = visibleSlots.find((slot) => !slot.isPrimary && !slot.value);
  if (emptyVisibleAdditional) {
    return {
      canConfirm: false,
      message: "Preencha ou remova o link adicional vazio antes de salvar a analise.",
      tone: "error",
    };
  }

  const invalidSlot = visibleSlots.find((slot) => slot.loading || !slot.preview);
  if (invalidSlot) {
    return {
      canConfirm: false,
      message: "Confirme todas as fontes visiveis antes de salvar a analise.",
      tone: invalidSlot.loading ? "loading" : "error",
    };
  }

  const primarySlot = getSlotState("primary");
  if (!primarySlot.preview || primarySlot.preview.monitoringType.id === "desconhecida") {
    return {
      canConfirm: false,
      message: "O link principal precisa identificar uma monitoracao valida.",
      tone: "error",
    };
  }

  if (primarySlot.preview.monitoringType.id === "sinalizacao_vertical") {
    const hasMeasurement = visibleSlots.some(
      (slot) => !slot.isPrimary && slot.preview?.sourceKind?.id === "medicao",
    );
    if (!hasMeasurement) {
      return {
        canConfirm: false,
        message: "Para Sinalizacao Vertical, adicione tambem uma fonte do tipo Medicao.",
        tone: "error",
      };
    }
  }

  return {
    canConfirm: true,
    message: "Todas as fontes foram confirmadas. Voce ja pode salvar a analise.",
    tone: "success",
  };
}

function confirmAnalysis(event) {
  event.preventDefault();

  const validation = validateAnalysisForm();
  if (!validation.canConfirm) {
    updateFormState();
    return;
  }

  const visibleSlots = state.sourceSlots.filter((slot) => slot.visible && slot.preview);
  const primarySlot = getSlotState("primary");
  const analysis = {
    id: createId(),
    createdAt: new Date().toISOString(),
    databaseName: primarySlot.preview.databaseName,
    monitoringId: primarySlot.preview.monitoringType.id,
    monitoringLabel: primarySlot.preview.monitoringType.label,
    roads: primarySlot.preview.roads,
    sources: visibleSlots.map((slot) => ({
      slot: slot.slot,
      isPrimary: slot.isPrimary,
      sheetUrl: slot.value,
      displayName: slot.preview.displayName,
      tabName: slot.preview.tabName,
      sourceKindId: slot.preview.sourceKind.id,
      sourceKindLabel: slot.preview.sourceKind.label,
      rowCount: slot.preview.rowCount,
    })),
  };

  state.analyses.unshift(analysis);
  saveAnalyses();
  renderAnalysisList();
  closeAnalysisDialog();
}

function openDeleteDialog() {
  if (!state.analyses.length) {
    return;
  }
  state.deleteSelection = new Set();
  renderDeleteList();
  elements.deleteDialog.showModal();
}

function closeDeleteDialog() {
  elements.deleteDialog.close();
}

function renderDeleteList() {
  elements.deleteList.innerHTML = "";

  for (const analysis of state.analyses) {
    const row = document.createElement("label");
    row.className = "checkbox-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = analysis.id;
    checkbox.checked = state.deleteSelection.has(analysis.id);
    checkbox.addEventListener("change", (event) => {
      if (event.target.checked) {
        state.deleteSelection.add(analysis.id);
      } else {
        state.deleteSelection.delete(analysis.id);
      }
      elements.confirmDeleteButton.disabled = !state.deleteSelection.size;
    });

    const content = document.createElement("div");
    content.className = "checkbox-content";

    const title = document.createElement("strong");
    title.textContent = analysis.databaseName;

    const subtitle = document.createElement("span");
    subtitle.textContent = analysis.sources.map((source) => source.tabName || source.sourceKindLabel || source.slot).join(" | ");

    content.append(title, subtitle);
    row.append(checkbox, content);
    elements.deleteList.append(row);
  }

  elements.confirmDeleteButton.disabled = !state.deleteSelection.size;
}

function confirmDeleteSelection(event) {
  event.preventDefault();
  if (!state.deleteSelection.size) {
    return;
  }

  state.analyses = state.analyses.filter((analysis) => !state.deleteSelection.has(analysis.id));
  saveAnalyses();
  renderAnalysisList();
  closeDeleteDialog();
}

function getSlotState(slotName) {
  return state.sourceSlots.find((slot) => slot.slot === slotName);
}

function getVisibleAdditionalSlots() {
  return state.sourceSlots.filter((slot) => !slot.isPrimary && slot.visible);
}

function clearSlotTimer(slotName) {
  if (state.slotTimers[slotName]) {
    window.clearTimeout(state.slotTimers[slotName]);
    delete state.slotTimers[slotName];
  }
}

function clearAllSlotTimers() {
  Object.keys(state.slotTimers).forEach(clearSlotTimer);
}

function setStatusElement(element, message, tone = "", loading = false) {
  element.className = "status";
  if (loading || tone === "loading") {
    element.classList.add("is-loading");
  } else if (tone) {
    element.classList.add(`is-${tone}`);
  }
  element.textContent = message;
}

function renderTagList(container, values) {
  container.innerHTML = "";
  values.forEach((value) => container.append(createTag(value)));
}

function createTag(label) {
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = label;
  return tag;
}

function createSourcePill(label) {
  const pill = document.createElement("span");
  pill.className = "source-pill";
  pill.textContent = label;
  return pill;
}

function createId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `analysis-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatDate(isoString) {
  const date = new Date(isoString);
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("pt-BR");
}
