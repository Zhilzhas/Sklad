const state = {
  invoices: [],
  wagons: [],
  assignmentItems: [],
};

const toast = document.getElementById("toast");

function showToast(text) {
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = "Ошибка запроса";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

function moneyTenge(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0.00 ₸";
  return `${num.toFixed(2)} ₸`;
}

function setDefaultDate() {
  const dateInput = document.querySelector("[name='issued_date']");
  if (!dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0, 10);
  }
}

function normalizeKzPhone(rawValue) {
  const digits = (rawValue || "").replace(/\D/g, "");
  const withoutCountry = digits.startsWith("7") ? digits.slice(1) : digits;
  return `+7${withoutCountry.slice(0, 10)}`;
}

function initPhoneInputs() {
  document.querySelectorAll(".kz-phone").forEach((input) => {
    input.addEventListener("input", () => {
      input.value = normalizeKzPhone(input.value);
    });
    input.addEventListener("focus", () => {
      if (!input.value || !input.value.startsWith("+7")) {
        input.value = "+7";
      }
    });
    input.addEventListener("blur", () => {
      if (input.value.length < 12) {
        input.setCustomValidity("Введите номер в формате +7XXXXXXXXXX");
      } else {
        input.setCustomValidity("");
      }
    });
  });
}

function toggleMeasureRequirements(row) {
  const measure = row.querySelector("[data-field='measure']").value;
  const weightInput = row.querySelector("[data-field='weight_kg']");
  const volumeInput = row.querySelector("[data-field='volume_m3']");

  if (measure === "weight") {
    weightInput.required = true;
    volumeInput.required = false;
  } else {
    weightInput.required = false;
    volumeInput.required = true;
  }
}

function renderItemRow(index) {
  const row = document.createElement("div");
  row.className = "item-row";
  row.innerHTML = `
    <div class="item-row-top">
      <strong>Позиция ${index}</strong>
      <button type="button" class="remove-item">Удалить</button>
    </div>
    <div class="item-grid">
      <label>Наименование
        <input data-field="name" required>
      </label>
      <label>Ед. измерения
        <input data-field="unit" placeholder="мешок, коробка..." required>
      </label>
      <label>Количество (шт.)
        <input type="number" min="1" step="1" data-field="quantity" required>
      </label>
      <label>Вес (кг)
        <input type="number" min="0" step="0.01" data-field="weight_kg" required>
      </label>
      <label>Объем (м³)
        <input type="number" min="0" step="0.01" data-field="volume_m3">
      </label>
      <label>Мера
        <select data-field="measure" required>
          <option value="weight">Вес</option>
          <option value="volume">Объем</option>
        </select>
      </label>
    </div>
  `;

  row.querySelector(".remove-item").addEventListener("click", () => {
    row.remove();
    reindexItemRows();
  });

  const measureSelect = row.querySelector("[data-field='measure']");
  measureSelect.addEventListener("change", () => toggleMeasureRequirements(row));
  toggleMeasureRequirements(row);
  return row;
}

function reindexItemRows() {
  document.querySelectorAll(".item-row").forEach((row, idx) => {
    row.querySelector("strong").textContent = `Позиция ${idx + 1}`;
  });
}

function addItemRow() {
  const wrap = document.getElementById("items-wrap");
  const nextIndex = wrap.querySelectorAll(".item-row").length + 1;
  wrap.appendChild(renderItemRow(nextIndex));
}

function gatherInvoicePayload() {
  const form = document.getElementById("invoice-form");
  const formData = new FormData(form);
  const items = [];

  document.querySelectorAll(".item-row").forEach((row) => {
    const quantity = Number.parseInt(row.querySelector("[data-field='quantity']").value, 10);
    const weight = Number(row.querySelector("[data-field='weight_kg']").value || 0);
    const volume = Number(row.querySelector("[data-field='volume_m3']").value || 0);
    const measure = row.querySelector("[data-field='measure']").value;

    items.push({
      name: row.querySelector("[data-field='name']").value.trim(),
      unit: row.querySelector("[data-field='unit']").value.trim(),
      quantity,
      weight_kg: Number(weight.toFixed(2)),
      volume_m3: Number(volume.toFixed(2)),
      measure,
    });
  });

  return {
    invoice_number: formData.get("invoice_number").trim(),
    issued_date: formData.get("issued_date"),
    shipper_name: formData.get("shipper_name").trim(),
    shipper_phone: normalizeKzPhone(formData.get("shipper_phone")),
    consignee_name: formData.get("consignee_name").trim(),
    consignee_phone: normalizeKzPhone(formData.get("consignee_phone")),
    items,
  };
}

function selectTab(tabName) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  });
}

function renderInvoices() {
  const container = document.getElementById("invoices-list");
  container.innerHTML = "";

  if (!state.invoices.length) {
    container.innerHTML = "<p>Накладных пока нет.</p>";
    return;
  }

  state.invoices.forEach((invoice) => {
    const card = document.createElement("div");
    card.className = "invoice-card";

    card.innerHTML = `
      <h3>№ ${invoice.invoice_number}</h3>
      <p>Дата: ${invoice.issued_date} | Строк: ${invoice.items_count}</p>
      <p>Отправитель: ${invoice.shipper_name}</p>
      <p>Получатель: ${invoice.consignee_name}</p>
      <p>Тариф: ${invoice.has_tariff ? "назначен" : "не назначен"} | Итог: ${moneyTenge(invoice.total_amount)}</p>
      <p>PDF: ${invoice.has_pdf ? "готов" : "не создан"}</p>
      <p>Создано: ${invoice.created_at}</p>
      <p>Изменено: ${invoice.updated_at}</p>
      <div class="row-actions">
        <button type="button" data-action="tariff">Тариф</button>
        <button type="button" data-action="wagon">Вагон</button>
        <button type="button" data-action="pdf">PDF</button>
      </div>
    `;

    card.querySelector("[data-action='tariff']").addEventListener("click", () => {
      document.getElementById("tariff-invoice-select").value = invoice.invoice_id;
      selectTab("tariffs");
    });

    card.querySelector("[data-action='wagon']").addEventListener("click", async () => {
      document.getElementById("assignment-invoice").value = invoice.invoice_id;
      await loadAssignmentItems();
      selectTab("wagons");
    });

    card.querySelector("[data-action='pdf']").addEventListener("click", () => {
      if (!invoice.has_tariff) {
        showToast("PDF доступен только после назначения тарифа");
        return;
      }
      window.open(`/api/invoices/${invoice.invoice_id}/pdf`, "_blank");
    });

    container.appendChild(card);
  });
}

function fillInvoiceSelects() {
  const selects = [
    document.getElementById("tariff-invoice-select"),
    document.getElementById("assignment-invoice"),
  ];

  selects.forEach((select) => {
    const previous = select.value;
    select.innerHTML = "<option value=''>Выберите накладную</option>";
    state.invoices.forEach((invoice) => {
      const option = document.createElement("option");
      option.value = invoice.invoice_id;
      option.textContent = `№ ${invoice.invoice_number} (${invoice.issued_date})`;
      select.appendChild(option);
    });
    if (previous && [...select.options].some((option) => option.value === previous)) {
      select.value = previous;
    }
  });
}

function fillWagonSelect() {
  const select = document.getElementById("assignment-wagon");
  const previous = select.value;
  select.innerHTML = "<option value=''>Выберите вагон</option>";
  state.wagons.forEach((wagon) => {
    const option = document.createElement("option");
    option.value = wagon.wagon_id;
    const destination = wagon.destination ? ` | ${wagon.destination}` : "";
    const description = wagon.description ? ` - ${wagon.description}` : "";
    option.textContent = `${wagon.wagon_code}${destination}${description}`;
    select.appendChild(option);
  });
  if (previous && [...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
}

async function loadInvoices() {
  const payload = await api("/api/invoices");
  state.invoices = payload.invoices || [];
  renderInvoices();
  fillInvoiceSelects();
}

async function loadWagons() {
  const payload = await api("/api/wagons");
  state.wagons = payload.wagons || [];
  fillWagonSelect();
}

function renderPartialItems() {
  const wrap = document.getElementById("partial-items");
  wrap.innerHTML = "";

  if (!state.assignmentItems.length) {
    wrap.innerHTML = "<p>Выберите накладную с позициями.</p>";
    return;
  }

  state.assignmentItems.forEach((item) => {
    const row = document.createElement("div");
    row.className = "partial-row";
    row.innerHTML = `
      <label class="partial-check">
        <input type="checkbox" data-partial-checkbox value="${item.item_id}">
        ${item.line_no}. ${item.name} (${item.unit}), доступно: ${item.quantity} шт.
      </label>
      <input type="number" min="1" max="${item.quantity}" step="1" value="1" data-partial-qty="${item.item_id}" disabled>
    `;
    const checkbox = row.querySelector("[data-partial-checkbox]");
    const qtyInput = row.querySelector(`[data-partial-qty="${item.item_id}"]`);
    checkbox.addEventListener("change", () => {
      qtyInput.disabled = !checkbox.checked;
      if (!checkbox.checked) qtyInput.value = 1;
    });
    wrap.appendChild(row);
  });
}

async function loadAssignmentItems() {
  const invoiceId = document.getElementById("assignment-invoice").value;
  state.assignmentItems = [];
  if (!invoiceId) {
    renderPartialItems();
    return;
  }
  const payload = await api(`/api/invoices/${invoiceId}`);
  state.assignmentItems = payload.items.map((item) => ({
    ...item,
    quantity: Number.parseInt(item.quantity, 10),
  }));
  renderPartialItems();
}

function togglePartialBox() {
  const fullyLoaded = document.getElementById("fully-loaded").value;
  const partialBox = document.getElementById("partial-box");
  partialBox.classList.toggle("hidden", fullyLoaded === "yes");
}

function collectPartialMovedItems() {
  const selected = [];
  document.querySelectorAll("[data-partial-checkbox]").forEach((checkbox) => {
    if (!checkbox.checked) return;
    const itemId = checkbox.value;
    const qtyInput = document.querySelector(`[data-partial-qty="${itemId}"]`);
    const movedQuantity = Number.parseInt(qtyInput.value, 10);
    selected.push({ item_id: itemId, moved_quantity: movedQuantity });
  });
  return selected;
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
  });
}

function initInvoiceForm() {
  document.getElementById("add-item-btn").addEventListener("click", addItemRow);
  addItemRow();

  document.getElementById("invoice-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = gatherInvoicePayload();
      if (!payload.items.length) {
        showToast("Добавьте хотя бы одну позицию");
        return;
      }

      if (!event.target.reportValidity()) {
        return;
      }

      await api("/api/invoices", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showToast("Накладная создана");
      event.target.reset();
      setDefaultDate();
      document.querySelectorAll(".kz-phone").forEach((input) => {
        input.value = "+7";
      });
      document.getElementById("items-wrap").innerHTML = "";
      addItemRow();
      await loadInvoices();
      selectTab("invoices");
    } catch (error) {
      showToast(error.message);
    }
  });
}

function initTariffForm() {
  document.getElementById("tariff-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const invoiceId = document.getElementById("tariff-invoice-select").value;
    if (!invoiceId) {
      showToast("Выберите накладную");
      return;
    }
    const body = {
      price_per_kg: Number(document.getElementById("price-per-kg").value),
      price_per_m3: Number(document.getElementById("price-per-m3").value),
    };
    try {
      const payload = await api(`/api/invoices/${invoiceId}/tariff`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const result = payload.invoice;
      document.getElementById("tariff-result").textContent =
        `Тариф назначен для накладной № ${result.invoice_number}. Итог: ${moneyTenge(result.total_amount)}. PDF обновлен.`;
      showToast("Тариф применен");
      await loadInvoices();
    } catch (error) {
      showToast(error.message);
    }
  });
}

function initWagonForms() {
  document.getElementById("wagon-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      wagon_code: document.getElementById("wagon-code").value.trim(),
      destination: document.getElementById("wagon-destination").value.trim(),
      description: document.getElementById("wagon-description").value.trim(),
    };
    try {
      await api("/api/wagons", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showToast("Вагон сохранен");
      event.target.reset();
      await loadWagons();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("assignment-invoice").addEventListener("change", loadAssignmentItems);
  document.getElementById("fully-loaded").addEventListener("change", togglePartialBox);
  togglePartialBox();

  document.getElementById("assignment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const invoiceId = document.getElementById("assignment-invoice").value;
    const wagonId = document.getElementById("assignment-wagon").value;
    const fullyLoadedValue = document.getElementById("fully-loaded").value;
    const fullyLoaded = fullyLoadedValue === "yes";
    const partialItems = collectPartialMovedItems();

    if (!invoiceId || !wagonId) {
      showToast("Выберите накладную и вагон");
      return;
    }
    if (!fullyLoaded && !partialItems.length) {
      showToast("Для частичной погрузки выберите хотя бы одну позицию");
      return;
    }

    try {
      const payload = await api("/api/wagon-assignments", {
        method: "POST",
        body: JSON.stringify({
          invoice_id: invoiceId,
          wagon_id: wagonId,
          fully_loaded: fullyLoaded,
          items: fullyLoaded ? [] : partialItems,
        }),
      });
      let message = "Распределение сохранено.";
      if (payload.new_invoice?.invoice?.invoice_number) {
        message += ` Создана новая накладная: № ${payload.new_invoice.invoice.invoice_number}.`;
      }
      document.getElementById("assignment-result").textContent = message;
      showToast("Распределение выполнено");
      await Promise.all([loadInvoices(), loadWagons()]);
      await loadAssignmentItems();
    } catch (error) {
      showToast(error.message);
    }
  });
}

function initTelegramWebApp() {
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }
}

async function bootstrap() {
  initTelegramWebApp();
  initTabs();
  setDefaultDate();
  initPhoneInputs();
  initInvoiceForm();
  initTariffForm();
  initWagonForms();

  document.getElementById("refresh-invoices").addEventListener("click", loadInvoices);
  await Promise.all([loadInvoices(), loadWagons()]);
}

bootstrap().catch((error) => {
  console.error(error);
  showToast("Ошибка инициализации");
});
