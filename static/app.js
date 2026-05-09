const state = {
  invoices: [],
  wagons: [],
  allocations: [],
  assignmentItems: [],
  itemTemplates: [],
  users: [],
  selectedArchiveInvoiceId: "",
  editingInvoiceId: "",
  user: null,
  submittingInvoice: false,
};

const toast = document.getElementById("toast");

function showToast(text) {
  if (!toast) return;
  toast.textContent = text;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2500);
}

function moneyTenge(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0.00 ₸";
  return `${num.toFixed(2)} ₸`;
}

function number2(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return "0.00";
  return num.toFixed(2);
}

function tokenGet() {
  return localStorage.getItem("sklad_token") || "";
}

function tokenSet(token) {
  localStorage.setItem("sklad_token", token);
}

function tokenClear() {
  localStorage.removeItem("sklad_token");
}

function setCurrentUserLabel() {
  const label = document.getElementById("current-user-label");
  const logoutBtn = document.getElementById("logout-btn");
  if (!label || !logoutBtn) return;
  if (!state.user) {
    label.textContent = "";
    label.classList.add("hidden");
    logoutBtn.classList.add("hidden");
    return;
  }
  const roleText = state.user.role === "admin" ? "админ" : "пользователь";
  label.textContent = `${state.user.login} (${roleText})`;
  label.classList.remove("hidden");
  logoutBtn.classList.remove("hidden");
}

async function api(path, options = {}, opts = {}) {
  const headers = { ...(options.headers || {}) };
  if (!opts.noAuth) {
    const token = tokenGet();
    if (!token) throw new Error("Требуется вход в систему");
    headers.Authorization = `Bearer ${token}`;
  }
  if (opts.idempotencyKey) {
    headers["X-Idempotency-Key"] = opts.idempotencyKey;
  }
  if (!headers["Content-Type"] && options.body) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = "Ошибка запроса";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      detail = response.statusText || detail;
    }
    if (response.status === 401) {
      tokenClear();
      showAuthScreen();
    }
    throw new Error(detail);
  }
  return response.json();
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
      if (!input.value || !input.value.startsWith("+7")) input.value = "+7";
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

function setDefaultDates() {
  const today = new Date().toISOString().slice(0, 10);
  const creationDate = document.querySelector("[name='creation_date']");
  const issuedDate = document.querySelector("[name='issued_date']");
  const estReleaseDate = document.getElementById("estimated-release-date");
  if (creationDate && !creationDate.value) creationDate.value = today;
  if (issuedDate && !issuedDate.value) issuedDate.value = today;
  if (estReleaseDate && !estReleaseDate.value) estReleaseDate.value = today;
}

function applyItemNameOptions() {
  const datalist = document.getElementById("item-name-options");
  if (!datalist) return;
  datalist.innerHTML = "";
  state.itemTemplates.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.name;
    datalist.appendChild(option);
  });
}

function templateByName(name) {
  const key = (name || "").trim().toLowerCase();
  return state.itemTemplates.find((x) => x.name.toLowerCase() === key) || null;
}

function applyTemplateToRow(row, template) {
  if (!template) return;
  const unit = row.querySelector("[data-field='unit']");
  const weight = row.querySelector("[data-field='weight_kg']");
  const volume = row.querySelector("[data-field='volume_m3']");
  if (unit) unit.value = template.unit || "";
  if (weight) weight.value = template.weight_kg || "";
  if (volume) volume.value = template.volume_m3 || "";
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

function CargoPositionCard(index, data = null) {
  const row = document.createElement("div");
  row.className = "item-row";
  row.innerHTML = `
    <div class="item-row-top">
      <strong>Позиция ${index}</strong>
      <button type="button" class="btn btn-ghost remove-item">Удалить</button>
    </div>
    <div class="item-grid">
      <label class="form-field">
        <span class="field-label">Наименование</span>
        <input data-field="name" list="item-name-options" required>
      </label>
      <label class="form-field">
        <span class="field-label">Ед. измерения</span>
        <input data-field="unit" placeholder="мешок, коробка..." required>
      </label>
      <label class="form-field">
        <span class="field-label">Количество (шт.)</span>
        <input type="number" min="1" step="1" data-field="quantity" required>
      </label>
      <label class="form-field">
        <span class="field-label">Вес (кг)</span>
        <input type="number" min="0" step="0.01" data-field="weight_kg" required>
      </label>
      <label class="form-field">
        <span class="field-label">Объем (м³)</span>
        <input type="number" min="0" step="0.01" data-field="volume_m3">
      </label>
      <label class="form-field">
        <span class="field-label">Мера</span>
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
  row.querySelector("[data-field='measure']").addEventListener("change", () => toggleMeasureRequirements(row));
  row.querySelector("[data-field='name']").addEventListener("change", (event) => {
    const tpl = templateByName(event.target.value);
    if (tpl) applyTemplateToRow(row, tpl);
  });
  row.querySelector("[data-field='name']").addEventListener("blur", (event) => {
    const tpl = templateByName(event.target.value);
    if (tpl) applyTemplateToRow(row, tpl);
  });

  if (data) {
    row.querySelector("[data-field='name']").value = data.name || "";
    row.querySelector("[data-field='unit']").value = data.unit || "";
    row.querySelector("[data-field='quantity']").value = data.quantity || "";
    row.querySelector("[data-field='weight_kg']").value = data.weight_kg || "";
    row.querySelector("[data-field='volume_m3']").value = data.volume_m3 || "";
    row.querySelector("[data-field='measure']").value = data.measure || "weight";
  }

  toggleMeasureRequirements(row);
  return row;
}

function reindexItemRows() {
  document.querySelectorAll(".item-row").forEach((row, idx) => {
    row.querySelector("strong").textContent = `Позиция ${idx + 1}`;
  });
}

function addItemRow({ atTop = true, data = null } = {}) {
  const wrap = document.getElementById("items-wrap");
  const row = CargoPositionCard(1, data);
  if (atTop) {
    wrap.prepend(row);
  } else {
    wrap.appendChild(row);
  }
  reindexItemRows();
}

function gatherInvoicePayload() {
  const form = document.getElementById("invoice-form");
  const formData = new FormData(form);
  const items = [];
  document.querySelectorAll(".item-row").forEach((row) => {
    items.push({
      name: row.querySelector("[data-field='name']").value.trim(),
      unit: row.querySelector("[data-field='unit']").value.trim(),
      quantity: Number.parseInt(row.querySelector("[data-field='quantity']").value, 10),
      weight_kg: Number((Number(row.querySelector("[data-field='weight_kg']").value || 0)).toFixed(2)),
      volume_m3: Number((Number(row.querySelector("[data-field='volume_m3']").value || 0)).toFixed(2)),
      measure: row.querySelector("[data-field='measure']").value,
    });
  });
  return {
    invoice_number: formData.get("invoice_number"),
    creation_date: formData.get("creation_date"),
    issued_date: formData.get("issued_date"),
    shipper_name: String(formData.get("shipper_name") || "").trim(),
    shipper_phone: normalizeKzPhone(formData.get("shipper_phone")),
    consignee_name: String(formData.get("consignee_name") || "").trim(),
    consignee_phone: normalizeKzPhone(formData.get("consignee_phone")),
    items,
  };
}

function generateIdempotencyKey() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `inv-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function setInvoiceFormMode() {
  const submitBtn = document.querySelector("#invoice-form button[type='submit']");
  const cancelBtn = document.getElementById("cancel-edit-btn");
  if (state.editingInvoiceId) {
    submitBtn.textContent = "Сохранить изменения";
    cancelBtn.classList.remove("hidden");
  } else {
    submitBtn.textContent = "Создать накладную";
    cancelBtn.classList.add("hidden");
  }
}

function resetInvoiceFormToCreate() {
  state.editingInvoiceId = "";
  const form = document.getElementById("invoice-form");
  form.reset();
  document.querySelectorAll(".kz-phone").forEach((input) => {
    input.value = "+7";
  });
  document.getElementById("items-wrap").innerHTML = "";
  addItemRow({ atTop: true });
  setDefaultDates();
  setInvoiceFormMode();
}

function selectTab(tabName) {
  if (tabName === "admin" && state.user?.role !== "admin") return;
  document.querySelectorAll(".bottom-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  });
}

function selectArchiveSubtab(tabName) {
  document.querySelectorAll(".archive-subtab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.archiveTab === tabName);
  });
  document.querySelectorAll(".archive-subpanel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `archive-subtab-${tabName}`);
  });
}

function ShipmentCard(invoice) {
  const card = document.createElement("div");
  card.className = "invoice-card";
  const tariffBadge = invoice.has_tariff
    ? `<span class="badge badge-accent">Тариф назначен</span>`
    : `<span class="badge badge-muted">Тариф не назначен</span>`;
  const pdfBadge = invoice.has_pdf
    ? `<span class="badge badge-accent">PDF готов</span>`
    : `<span class="badge badge-muted">PDF не готов</span>`;
  const wagonBadge = invoice.estimated_release_date
    ? `<span class="badge badge-accent">Выдача: ${invoice.estimated_release_date}</span>`
    : `<span class="badge badge-muted">Вагон не назначен</span>`;

  const adminActions =
    state.user?.role === "admin"
      ? `
      <button type="button" class="btn btn-secondary" data-action="edit">Редактировать</button>
      <button type="button" class="btn btn-ghost" data-action="delete">Удалить</button>
    `
      : "";

  card.innerHTML = `
    <h3 class="invoice-title">Накладная № ${invoice.invoice_number}</h3>
    <p class="invoice-meta"><span class="meta-strong">Создана:</span> ${invoice.creation_date || "-"} | <span class="meta-strong">Дата накладной:</span> ${invoice.issued_date || "-"}</p>
    <p class="invoice-meta"><span class="meta-strong">Отправитель:</span> ${invoice.shipper_name}</p>
    <p class="invoice-meta"><span class="meta-strong">Получатель:</span> ${invoice.consignee_name}</p>
    <p class="invoice-meta"><span class="meta-strong">Строк:</span> ${invoice.items_count} | <span class="meta-strong">Кол-во:</span> ${invoice.total_quantity} | <span class="meta-strong">Вес:</span> ${number2(invoice.total_weight_kg)} кг | <span class="meta-strong">Объем:</span> ${number2(invoice.total_volume_m3)} м³</p>
    <p class="invoice-meta"><span class="meta-strong">Итог:</span> ${moneyTenge(invoice.total_amount)}</p>
    <div class="badge-row">${tariffBadge}${pdfBadge}${wagonBadge}</div>
    <div class="row-actions">
      <button type="button" class="btn btn-secondary" data-action="tariff">Тариф</button>
      <button type="button" class="btn btn-secondary" data-action="wagon">Вагон</button>
      <button type="button" class="btn btn-primary" data-action="pdf">PDF</button>
      ${adminActions}
    </div>
  `;

  card.querySelector("[data-action='tariff']").addEventListener("click", () => {
    document.getElementById("tariff-invoice-select").value = invoice.invoice_id;
    document.getElementById("price-per-kg").focus();
    selectTab("create");
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
    const token = encodeURIComponent(tokenGet());
    window.open(`/api/invoices/${invoice.invoice_id}/pdf?token=${token}`, "_blank");
  });

  if (state.user?.role === "admin") {
    card.querySelector("[data-action='edit']").addEventListener("click", () => startInvoiceEdit(invoice.invoice_id));
    card.querySelector("[data-action='delete']").addEventListener("click", () => deleteInvoice(invoice.invoice_id));
  }
  return card;
}

function renderInvoices() {
  const container = document.getElementById("invoices-list");
  container.innerHTML = "";
  const filtered = applyInvoiceFilters(state.invoices);
  if (!filtered.length) {
    container.innerHTML = state.invoices.length
      ? "<p class='status-text'>По выбранным фильтрам ничего не найдено.</p>"
      : "<p class='status-text'>Накладных пока нет.</p>";
    return;
  }
  filtered.forEach((invoice) => container.appendChild(ShipmentCard(invoice)));
}

function fillInvoiceSelects() {
  const selects = [document.getElementById("tariff-invoice-select"), document.getElementById("assignment-invoice")];
  selects.forEach((select) => {
    const prev = select.value;
    select.innerHTML = "<option value=''>Выберите накладную</option>";
    state.invoices.forEach((invoice) => {
      const option = document.createElement("option");
      option.value = invoice.invoice_id;
      option.textContent = `№ ${invoice.invoice_number} (${invoice.creation_date || invoice.issued_date})`;
      select.appendChild(option);
    });
    if (prev && [...select.options].some((x) => x.value === prev)) select.value = prev;
  });
}

function fillWagonSelect() {
  const select = document.getElementById("assignment-wagon");
  const prev = select.value;
  select.innerHTML = "<option value=''>Выберите вагон</option>";
  state.wagons.forEach((wagon) => {
    const option = document.createElement("option");
    option.value = wagon.wagon_id;
    option.textContent = `${wagon.wagon_code}${wagon.destination ? ` | ${wagon.destination}` : ""}`;
    select.appendChild(option);
  });
  if (prev && [...select.options].some((x) => x.value === prev)) select.value = prev;
}

function applyArchiveFilters(source) {
  const invoiceNumber = document.getElementById("f-invoice-number").value.trim().toLowerCase();
  const shipper = document.getElementById("f-shipper").value.trim().toLowerCase();
  const consignee = document.getElementById("f-consignee").value.trim().toLowerCase();
  const createdFrom = document.getElementById("f-created-from").value;
  const createdTo = document.getElementById("f-created-to").value;
  const hasTariff = document.getElementById("f-has-tariff").value;

  return source.filter((row) => {
    if (invoiceNumber && !row.invoice_number.toLowerCase().includes(invoiceNumber)) return false;
    if (shipper && !row.shipper_name.toLowerCase().includes(shipper)) return false;
    if (consignee && !row.consignee_name.toLowerCase().includes(consignee)) return false;
    if (createdFrom && (row.creation_date || "") < createdFrom) return false;
    if (createdTo && (row.creation_date || "") > createdTo) return false;
    if (hasTariff === "yes" && !row.has_tariff) return false;
    if (hasTariff === "no" && row.has_tariff) return false;
    return true;
  });
}

function applyInvoiceFilters(source) {
  const number = document.getElementById("inv-f-number").value.trim().toLowerCase();
  const shipper = document.getElementById("inv-f-shipper").value.trim().toLowerCase();
  const consignee = document.getElementById("inv-f-consignee").value.trim().toLowerCase();
  const createdFrom = document.getElementById("inv-f-created-from").value;
  const createdTo = document.getElementById("inv-f-created-to").value;
  const hasTariff = document.getElementById("inv-f-has-tariff").value;

  return source.filter((row) => {
    if (number && !row.invoice_number.toLowerCase().includes(number)) return false;
    if (shipper && !row.shipper_name.toLowerCase().includes(shipper)) return false;
    if (consignee && !row.consignee_name.toLowerCase().includes(consignee)) return false;
    if (createdFrom && (row.creation_date || "") < createdFrom) return false;
    if (createdTo && (row.creation_date || "") > createdTo) return false;
    if (hasTariff === "yes" && !row.has_tariff) return false;
    if (hasTariff === "no" && row.has_tariff) return false;
    return true;
  });
}

function renderArchive() {
  const body = document.getElementById("archive-body");
  body.innerHTML = "";
  const filtered = applyArchiveFilters(state.invoices);

  let totalLines = 0;
  let totalQty = 0;
  let totalWeight = 0;
  let totalVolume = 0;
  let totalMoney = 0;

  if (!filtered.length) {
    body.innerHTML = "<tr><td colspan='12'>Нет данных по выбранным фильтрам</td></tr>";
  } else {
    filtered.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><button type="button" class="archive-link-btn" data-invoice-id="${row.invoice_id}">${row.invoice_number}</button></td>
        <td>${row.creation_date || "-"}</td>
        <td>${row.issued_date || "-"}</td>
        <td>${row.estimated_release_date || "-"}</td>
        <td>${row.shipper_name}</td>
        <td>${row.consignee_name}</td>
        <td>${row.items_count}</td>
        <td>${row.total_quantity}</td>
        <td>${number2(row.total_weight_kg)}</td>
        <td>${number2(row.total_volume_m3)}</td>
        <td>${moneyTenge(row.total_amount)}</td>
        <td>${row.has_tariff ? "Да" : "Нет"}</td>
      `;
      body.appendChild(tr);

      totalLines += Number(row.items_count || 0);
      totalQty += Number(row.total_quantity || 0);
      totalWeight += Number(row.total_weight_kg || 0);
      totalVolume += Number(row.total_volume_m3 || 0);
      totalMoney += Number(row.total_amount || 0);
    });
  }

  document.getElementById("archive-total-lines").textContent = String(totalLines);
  document.getElementById("archive-total-qty").textContent = String(totalQty);
  document.getElementById("archive-total-weight").textContent = number2(totalWeight);
  document.getElementById("archive-total-volume").textContent = number2(totalVolume);
  document.getElementById("archive-total-money").textContent = moneyTenge(totalMoney);
}

function renderArchiveWagonsTable() {
  const body = document.getElementById("archive-wagons-body");
  body.innerHTML = "";

  const invoicesById = Object.fromEntries(state.invoices.map((x) => [x.invoice_id, x]));
  const wagonsById = Object.fromEntries(state.wagons.map((x) => [x.wagon_id, x]));
  const grouped = new Map();

  state.allocations.forEach((alloc) => {
    const key = `${alloc.wagon_id}::${alloc.invoice_id}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        wagon: wagonsById[alloc.wagon_id] || null,
        invoice: invoicesById[alloc.invoice_id] || null,
        allocatedTotal: 0,
        entries: 0,
      });
    }
    const row = grouped.get(key);
    row.allocatedTotal += Number(alloc.allocation_value || 0);
    row.entries += 1;
  });

  let totalAllocated = 0;
  let totalEntries = 0;

  if (!grouped.size) {
    body.innerHTML = "<tr><td colspan='7'>Пока нет распределений по вагонам</td></tr>";
  } else {
    [...grouped.values()].forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.wagon?.wagon_code || "-"}</td>
        <td>${row.wagon?.destination || "-"}</td>
        <td>${row.invoice?.invoice_number || "-"}</td>
        <td>${row.invoice?.shipper_name || "-"}</td>
        <td>${row.invoice?.consignee_name || "-"}</td>
        <td>${number2(row.allocatedTotal)}</td>
        <td>${row.entries}</td>
      `;
      body.appendChild(tr);
      totalAllocated += row.allocatedTotal;
      totalEntries += row.entries;
    });
  }

  document.getElementById("archive-wagons-total-allocated").textContent = number2(totalAllocated);
  document.getElementById("archive-wagons-total-entries").textContent = String(totalEntries);
}

async function loadArchiveInvoiceDetails(invoiceId) {
  state.selectedArchiveInvoiceId = invoiceId;
  const empty = document.getElementById("archive-details-empty");
  const content = document.getElementById("archive-details-content");
  const meta = document.getElementById("archive-details-meta");
  const itemsBody = document.getElementById("archive-details-items");

  try {
    const payload = await api(`/api/invoices/${invoiceId}`);
    const invoice = payload.invoice;
    const items = payload.items || [];
    const allocations = payload.allocations || [];
    const wagonsById = Object.fromEntries(state.wagons.map((w) => [w.wagon_id, w]));
    const directions = new Set(
      allocations
        .map((a) => wagonsById[a.wagon_id]?.destination || wagonsById[a.wagon_id]?.wagon_code)
        .filter(Boolean),
    );

    meta.innerHTML = `
      <p class="invoice-meta"><span class="meta-strong">Накладная:</span> № ${invoice.invoice_number}</p>
      <p class="invoice-meta"><span class="meta-strong">Отправитель:</span> ${invoice.shipper_name}</p>
      <p class="invoice-meta"><span class="meta-strong">Получатель:</span> ${invoice.consignee_name}</p>
      <p class="invoice-meta"><span class="meta-strong">Куда едет:</span> ${directions.size ? [...directions].join(", ") : "-"}</p>
      <p class="invoice-meta"><span class="meta-strong">Создана:</span> ${invoice.creation_date || "-"} | <span class="meta-strong">Дата накладной:</span> ${invoice.issued_date || "-"}</p>
      <p class="invoice-meta"><span class="meta-strong">План выдачи:</span> ${invoice.estimated_release_date || "-"}</p>
      <p class="invoice-meta"><span class="meta-strong">Тариф за 1 кг:</span> ${moneyTenge(invoice.tariff_price_per_kg || 0)} | <span class="meta-strong">Тариф за 1 м³:</span> ${moneyTenge(invoice.tariff_price_per_m3 || 0)}</p>
      <p class="invoice-meta"><span class="meta-strong">Итог:</span> ${moneyTenge(invoice.total_amount || 0)}</p>
    `;

    itemsBody.innerHTML = "";

    let totalQty = 0;
    let totalWeight = 0;
    let totalVolume = 0;
    let totalMoney = 0;

    if (!items.length) {
      itemsBody.innerHTML = "<tr><td colspan='9'>В накладной нет позиций</td></tr>";
    } else {
      items.forEach((item) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${item.line_no}</td>
          <td>${item.name}</td>
          <td>${item.unit}</td>
          <td>${item.quantity}</td>
          <td>${item.weight_kg}</td>
          <td>${item.volume_m3}</td>
          <td>${item.measure === "weight" ? "Вес" : "Объем"}</td>
          <td>${moneyTenge(item.unit_price || 0)}</td>
          <td>${moneyTenge(item.line_total || 0)}</td>
        `;
        itemsBody.appendChild(tr);

        totalQty += Number(item.quantity || 0);
        totalWeight += Number(item.weight_kg || 0);
        totalVolume += Number(item.volume_m3 || 0);
        totalMoney += Number(item.line_total || 0);
      });
    }

    document.getElementById("details-total-qty").textContent = String(totalQty);
    document.getElementById("details-total-weight").textContent = number2(totalWeight);
    document.getElementById("details-total-volume").textContent = number2(totalVolume);
    document.getElementById("details-total-money").textContent = moneyTenge(totalMoney);

    empty.classList.add("hidden");
    content.classList.remove("hidden");
    selectArchiveSubtab("details");
  } catch (error) {
    showToast(error.message);
  }
}

async function loadInvoices() {
  const payload = await api("/api/invoices");
  state.invoices = payload.invoices || [];
  renderInvoices();
  fillInvoiceSelects();
  renderArchive();
  renderArchiveWagonsTable();
}

async function loadWagons() {
  const payload = await api("/api/wagons");
  state.wagons = payload.wagons || [];
  fillWagonSelect();
  renderArchiveWagonsTable();
}

async function loadAllocations() {
  const payload = await api("/api/allocations");
  state.allocations = payload.allocations || [];
  renderArchiveWagonsTable();
}

async function loadNextNumbers() {
  const payload = await api("/api/next-numbers");
  const invoiceInput = document.getElementById("invoice-number");
  const wagonInput = document.getElementById("wagon-code");
  if (invoiceInput && !state.editingInvoiceId) invoiceInput.value = payload.next_invoice_number || "";
  if (wagonInput) wagonInput.value = payload.next_wagon_code || "";
}

async function loadItemTemplates() {
  const payload = await api("/api/item-templates");
  state.itemTemplates = payload.templates || [];
  applyItemNameOptions();
}

async function loadUsers() {
  if (state.user?.role !== "admin") return;
  const payload = await api("/api/admin/users");
  state.users = payload.users || [];
  renderUsers();
}

function renderUsers() {
  const body = document.getElementById("admin-users-body");
  body.innerHTML = "";
  if (!state.users.length) {
    body.innerHTML = "<tr><td colspan='3'>Пользователи не найдены</td></tr>";
    return;
  }

  state.users.forEach((user) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${user.login}</td>
      <td>${user.role === "admin" ? "Админ" : "Пользователь"}</td>
      <td>
        <div class="action-row">
          <select data-role-select="${user.user_id}">
            <option value="user" ${user.role === "user" ? "selected" : ""}>Пользователь</option>
            <option value="admin" ${user.role === "admin" ? "selected" : ""}>Админ</option>
          </select>
          <button type="button" class="btn btn-secondary" data-role-save="${user.user_id}">Сохранить</button>
        </div>
      </td>
    `;
    body.appendChild(tr);
  });

  body.querySelectorAll("[data-role-save]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const userId = btn.getAttribute("data-role-save");
      const select = body.querySelector(`[data-role-select='${userId}']`);
      try {
        await api(`/api/admin/users/${userId}/role`, {
          method: "PATCH",
          body: JSON.stringify({ role: select.value }),
        });
        showToast("Роль обновлена");
        await loadUsers();
      } catch (error) {
        showToast(error.message);
      }
    });
  });
}

function renderPartialItems() {
  const wrap = document.getElementById("partial-items");
  wrap.innerHTML = "";
  if (!state.assignmentItems.length) {
    wrap.innerHTML = "<p class='status-text'>Выберите накладную с позициями.</p>";
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
    const cb = row.querySelector("[data-partial-checkbox]");
    const qty = row.querySelector(`[data-partial-qty="${item.item_id}"]`);
    cb.addEventListener("change", () => {
      qty.disabled = !cb.checked;
      if (!cb.checked) qty.value = 1;
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
  state.assignmentItems = payload.items.map((x) => ({ ...x, quantity: Number.parseInt(x.quantity, 10) }));
  renderPartialItems();
}

function togglePartialBox() {
  document.getElementById("partial-box").classList.toggle("hidden", document.getElementById("fully-loaded").value === "yes");
}

function collectPartialMovedItems() {
  const selected = [];
  document.querySelectorAll("[data-partial-checkbox]").forEach((cb) => {
    if (!cb.checked) return;
    const qty = Number.parseInt(document.querySelector(`[data-partial-qty="${cb.value}"]`).value, 10);
    selected.push({ item_id: cb.value, moved_quantity: qty });
  });
  return selected;
}

async function startInvoiceEdit(invoiceId) {
  if (state.user?.role !== "admin") return;
  try {
    const payload = await api(`/api/invoices/${invoiceId}`);
    const invoice = payload.invoice;
    const items = payload.items || [];

    state.editingInvoiceId = invoiceId;
    document.getElementById("invoice-number").value = invoice.invoice_number || "";
    document.querySelector("[name='creation_date']").value = invoice.creation_date || "";
    document.querySelector("[name='issued_date']").value = invoice.issued_date || "";
    document.querySelector("[name='shipper_name']").value = invoice.shipper_name || "";
    document.querySelector("[name='shipper_phone']").value = invoice.shipper_phone || "+7";
    document.querySelector("[name='consignee_name']").value = invoice.consignee_name || "";
    document.querySelector("[name='consignee_phone']").value = invoice.consignee_phone || "+7";

    const wrap = document.getElementById("items-wrap");
    wrap.innerHTML = "";
    items.forEach((item) => addItemRow({ atTop: false, data: item }));
    if (!items.length) addItemRow({ atTop: true });

    setInvoiceFormMode();
    selectTab("create");
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteInvoice(invoiceId) {
  if (state.user?.role !== "admin") return;
  if (!window.confirm("Удалить накладную? Это действие необратимо.")) return;
  try {
    await api(`/api/invoices/${invoiceId}`, { method: "DELETE" });
    showToast("Накладная удалена");
    if (state.editingInvoiceId === invoiceId) {
      resetInvoiceFormToCreate();
      await loadNextNumbers();
    }
    await Promise.all([loadInvoices(), loadAllocations(), loadItemTemplates(), loadNextNumbers()]);
  } catch (error) {
    showToast(error.message);
  }
}

function initTabs() {
  document.querySelectorAll(".bottom-tab").forEach((button) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
  });
}

function initInvoiceForm() {
  document.getElementById("add-item-btn").addEventListener("click", () => addItemRow({ atTop: true }));
  addItemRow({ atTop: true });

  document.getElementById("cancel-edit-btn").addEventListener("click", async () => {
    resetInvoiceFormToCreate();
    await loadNextNumbers();
  });

  document.getElementById("invoice-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.submittingInvoice) return;
    if (!event.target.reportValidity()) return;

    const submitBtn = event.target.querySelector("button[type='submit']");
    const originalText = submitBtn.textContent;
    state.submittingInvoice = true;
    submitBtn.disabled = true;
    submitBtn.textContent = state.editingInvoiceId ? "Сохраняем..." : "Создаем...";

    try {
      const payload = gatherInvoicePayload();
      if (!payload.items.length) {
        showToast("Добавьте хотя бы одну позицию");
        return;
      }

      if (state.editingInvoiceId) {
        await api(`/api/invoices/${state.editingInvoiceId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        showToast("Накладная обновлена");
      } else {
        await api(
          "/api/invoices",
          { method: "POST", body: JSON.stringify(payload) },
          { idempotencyKey: generateIdempotencyKey() },
        );
        showToast("Накладная создана");
      }

      resetInvoiceFormToCreate();
      await Promise.all([loadInvoices(), loadAllocations(), loadNextNumbers(), loadItemTemplates()]);
      selectTab("invoices");
    } catch (error) {
      showToast(error.message);
    } finally {
      state.submittingInvoice = false;
      submitBtn.disabled = false;
      submitBtn.textContent = originalText;
      setInvoiceFormMode();
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
    try {
      const payload = await api(`/api/invoices/${invoiceId}/tariff`, {
        method: "POST",
        body: JSON.stringify({
          price_per_kg: Number(document.getElementById("price-per-kg").value),
          price_per_m3: Number(document.getElementById("price-per-m3").value),
        }),
      });
      document.getElementById("tariff-result").textContent = `Тариф назначен для накладной № ${payload.invoice.invoice_number}. Итог: ${moneyTenge(payload.invoice.total_amount)}.`;
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
    try {
      await api("/api/wagons", {
        method: "POST",
        body: JSON.stringify({
          wagon_code: document.getElementById("wagon-code").value.trim(),
          destination: document.getElementById("wagon-destination").value.trim(),
          description: document.getElementById("wagon-description").value.trim(),
        }),
      });
      showToast("Вагон сохранен");
      event.target.reset();
      await Promise.all([loadWagons(), loadNextNumbers()]);
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
    const estimatedReleaseDate = document.getElementById("estimated-release-date").value;
    const fullyLoaded = document.getElementById("fully-loaded").value === "yes";
    const partialItems = collectPartialMovedItems();

    if (!invoiceId || !wagonId || !estimatedReleaseDate) {
      showToast("Заполните накладную, вагон и дату выдачи");
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
          estimated_release_date: estimatedReleaseDate,
          fully_loaded: fullyLoaded,
          items: fullyLoaded ? [] : partialItems,
        }),
      });
      let msg = "Распределение сохранено.";
      if (payload.new_invoice?.invoice?.invoice_number) {
        msg += ` Создана новая накладная: № ${payload.new_invoice.invoice.invoice_number}.`;
      }
      document.getElementById("assignment-result").textContent = msg;
      showToast("Распределение выполнено");
      await Promise.all([loadInvoices(), loadWagons(), loadAllocations(), loadNextNumbers(), loadItemTemplates()]);
      await loadAssignmentItems();
    } catch (error) {
      showToast(error.message);
    }
  });
}

function initArchiveSection() {
  document.querySelectorAll(".archive-subtab").forEach((button) => {
    button.addEventListener("click", () => selectArchiveSubtab(button.dataset.archiveTab));
  });

  document.getElementById("archive-body").addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const invoiceId = target.getAttribute("data-invoice-id");
    if (!invoiceId) return;
    loadArchiveInvoiceDetails(invoiceId);
  });
}

function initArchiveFilters() {
  ["f-invoice-number", "f-shipper", "f-consignee", "f-created-from", "f-created-to", "f-has-tariff"].forEach((id) => {
    document.getElementById(id).addEventListener("input", renderArchive);
    document.getElementById(id).addEventListener("change", renderArchive);
  });
  document.getElementById("clear-archive-filters").addEventListener("click", () => {
    document.getElementById("archive-filter-form").reset();
    renderArchive();
  });
}

function initInvoiceFilters() {
  [
    "inv-f-number",
    "inv-f-shipper",
    "inv-f-consignee",
    "inv-f-created-from",
    "inv-f-created-to",
    "inv-f-has-tariff",
  ].forEach((id) => {
    document.getElementById(id).addEventListener("input", renderInvoices);
    document.getElementById(id).addEventListener("change", renderInvoices);
  });
  document.getElementById("clear-invoice-filters").addEventListener("click", () => {
    document.getElementById("invoices-filter-form").reset();
    renderInvoices();
  });
}

function initAdminSection() {
  document.getElementById("admin-user-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({
          login: document.getElementById("admin-new-login").value.trim(),
          password: document.getElementById("admin-new-password").value,
          role: document.getElementById("admin-new-role").value,
        }),
      });
      showToast("Пользователь создан");
      event.target.reset();
      await loadUsers();
    } catch (error) {
      showToast(error.message);
    }
  });
}

function applyRoleUi() {
  const isAdmin = state.user?.role === "admin";
  const navAdmin = document.getElementById("nav-admin");
  const tabAdmin = document.getElementById("tab-admin");
  if (isAdmin) {
    navAdmin.classList.remove("hidden");
    tabAdmin.classList.remove("hidden");
  } else {
    navAdmin.classList.add("hidden");
    tabAdmin.classList.add("hidden");
    if (tabAdmin.classList.contains("active")) {
      selectTab("create");
    }
  }
}

function initTelegramWebApp() {
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }
}

function showAuthScreen() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.querySelector(".app-shell").classList.add("hidden");
  setCurrentUserLabel();
}

function showAppScreen() {
  document.getElementById("login-screen").classList.add("hidden");
  document.querySelector(".app-shell").classList.remove("hidden");
  setCurrentUserLabel();
}

function initLoginForm() {
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorBox = document.getElementById("login-error");
    errorBox.textContent = "";
    try {
      const payload = await api(
        "/api/auth/login",
        {
          method: "POST",
          body: JSON.stringify({
            login: document.getElementById("login-name").value.trim(),
            password: document.getElementById("login-password").value,
          }),
        },
        { noAuth: true },
      );
      tokenSet(payload.token);
      state.user = payload.user;
      applyRoleUi();
      setCurrentUserLabel();
      showAppScreen();
      await bootstrapData();
      showToast(`Вы вошли как ${state.user.login}`);
    } catch (error) {
      errorBox.textContent = error.message;
    }
  });
}

async function bootstrapData() {
  await Promise.all([loadInvoices(), loadWagons(), loadAllocations(), loadNextNumbers(), loadItemTemplates()]);
  if (state.user?.role === "admin") {
    await loadUsers();
  }
}

async function restoreSession() {
  const token = tokenGet();
  if (!token) return false;
  try {
    const payload = await api("/api/auth/me");
    state.user = payload.user;
    applyRoleUi();
    setCurrentUserLabel();
    showAppScreen();
    await bootstrapData();
    return true;
  } catch (_) {
    tokenClear();
    state.user = null;
    return false;
  }
}

async function bootstrap() {
  initTelegramWebApp();
  initTabs();
  initPhoneInputs();
  initInvoiceForm();
  initTariffForm();
  initWagonForms();
  initArchiveSection();
  initArchiveFilters();
  initInvoiceFilters();
  initAdminSection();
  initLoginForm();
  document.getElementById("logout-btn").addEventListener("click", () => {
    tokenClear();
    state.user = null;
    state.editingInvoiceId = "";
    state.invoices = [];
    state.wagons = [];
    state.allocations = [];
    state.assignmentItems = [];
    state.itemTemplates = [];
    state.users = [];
    setCurrentUserLabel();
    showAuthScreen();
  });
  setDefaultDates();
  setInvoiceFormMode();

  document.getElementById("refresh-invoices").addEventListener("click", async () => {
    await Promise.all([loadInvoices(), loadAllocations(), loadItemTemplates()]);
  });

  showAuthScreen();
  const restored = await restoreSession();
  if (!restored) {
    showAuthScreen();
  }
}

bootstrap().catch((error) => {
  console.error(error);
  showToast("Ошибка инициализации");
});
