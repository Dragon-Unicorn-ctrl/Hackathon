const state = {
  token: localStorage.getItem("fleet_token"),
  user: null,
  map: null,
  vehicleMarkers: null,
  shipmentMarkers: null,
  routeLayer: null,
  selectedVehicleId: null,
  vehicles: [],
  shipments: [],
  summary: null,
  charts: {},
  refreshTimer: null,
};

const statusColors = {
  vehicle: {
    available: "#22c55e",
    en_route: "#3b82f6",
    maintenance: "#ef4444",
  },
  shipment: {
    pending: "#f59e0b",
    assigned: "#8b5cf6",
    in_transit: "#3b82f6",
    delivered: "#22c55e",
    exception: "#ef4444",
  },
};

document.addEventListener("DOMContentLoaded", init);

function init() {
  bindEvents();

  if (state.token) {
    api("/api/auth/me")
      .then((user) => {
        state.user = user;
        showApp();
      })
      .catch(() => logout());
  }
}

function bindEvents() {
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", handleLogin);
  }

  const logoutBtn = document.getElementById("btn-logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", logout);
  }

  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.page));
  });

  const refreshBtn = document.getElementById("btn-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", loadAll);
  }

  const simulateBtn = document.getElementById("btn-simulate");
  if (simulateBtn) {
    simulateBtn.addEventListener("click", async () => {
      try {
        await api("/api/simulate/gps", { method: "POST" });
        showToast("GPS simulation completed");
        await loadAll();
      } catch (error) {
        showToast(error.message, "error");
      }
    });
  }

  const autoAssignBtn = document.getElementById("btn-auto-assign");
  if (autoAssignBtn) {
    autoAssignBtn.addEventListener("click", async () => {
      try {
        const result = await api("/api/shipments/auto-assign", { method: "POST" });
        showToast(`Assigned ${result.assigned_count} shipment(s)`);
        await loadAll();
      } catch (error) {
        showToast(error.message, "error");
      }
    });
  }

  const newShipmentBtn = document.getElementById("btn-new-shipment");
  if (newShipmentBtn) {
    newShipmentBtn.addEventListener("click", () => openShipmentModal());
  }

  const newVehicleBtn = document.getElementById("btn-new-vehicle");
  if (newVehicleBtn) {
    newVehicleBtn.addEventListener("click", () => openVehicleModal());
  }

  let searchTimer;
  const searchInput = document.getElementById("shipment-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(async () => {
        try {
          await loadShipmentsData();
          renderShipments();
          updateMap();
        } catch (error) {
          showToast(error.message, "error");
        }
      }, 350);
    });
  }

  const statusFilter = document.getElementById("shipment-status-filter");
  if (statusFilter) {
    statusFilter.addEventListener("change", async () => {
      try {
        await loadShipmentsData();
        renderShipments();
        updateMap();
      } catch (error) {
        showToast(error.message, "error");
      }
    });
  }

  const modalClose = document.getElementById("modal-close");
  if (modalClose) {
    modalClose.addEventListener("click", closeModal);
  }
}

async function handleLogin(event) {
  event.preventDefault();

  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");

  try {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Login failed");
    }

    state.token = data.access_token;
    state.user = data.user;
    localStorage.setItem("fleet_token", state.token);

    errorEl.classList.add("hidden");
    showApp();
  } catch (error) {
    errorEl.textContent = error.message;
    errorEl.classList.remove("hidden");
  }
}

function logout() {
  localStorage.removeItem("fleet_token");
  state.token = null;
  state.user = null;

  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }

  document.getElementById("app").classList.add("hidden");
  document.getElementById("login-screen").classList.remove("hidden");
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");

  document.getElementById("current-user").textContent = state.user
    ? `${state.user.name} (${state.user.role})`
    : "";

  initMap();

  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
  }

  state.refreshTimer = setInterval(loadAll, 10000);
  loadAll();
}

async function api(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
  };

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  if (response.status === 401 && !path.startsWith("/api/auth/login")) {
    logout();
    throw new Error("Session expired");
  }

  if (!response.ok) {
    let detail = response.statusText;

    try {
      const data = await response.json();
      detail = data.detail || JSON.stringify(data);
    } catch (error) {
      // Keep default status text.
    }

    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function loadSummaryData() {
  state.summary = await api("/api/dashboard/summary");
}

async function loadVehiclesData() {
  state.vehicles = await api("/api/vehicles");
}

async function loadShipmentsData() {
  const params = new URLSearchParams();

  const q = document.getElementById("shipment-search")?.value?.trim();
  const statusValue = document.getElementById("shipment-status-filter")?.value;

  if (q) {
    params.set("q", q);
  }

  if (statusValue) {
    params.set("status", statusValue);
  }

  state.shipments = await api(`/api/shipments?${params.toString()}`);
}

async function loadAll() {
  try {
    await Promise.all([
      loadSummaryData(),
      loadVehiclesData(),
      loadShipmentsData(),
    ]);

    renderDashboard();
    renderVehicles();
    renderShipments();
    updateMap();
  } catch (error) {
    console.error(error);

    if (error.message !== "Session expired") {
      showToast(error.message, "error");
    }
  }
}

function initMap() {
  if (state.map || typeof L === "undefined") {
    return;
  }

  state.map = L.map("fleet-map").setView([41.8781, -87.6298], 12);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(state.map);

  state.vehicleMarkers = L.layerGroup().addTo(state.map);
  state.shipmentMarkers = L.layerGroup().addTo(state.map);
  state.routeLayer = L.layerGroup().addTo(state.map);
}

function showPage(page) {
  document.querySelectorAll(".page").forEach((element) => {
    element.classList.remove("active");
  });

  const target = document.getElementById(page);
  if (target) {
    target.classList.add("active");
  }

  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === page);
  });

  const titles = {
    dashboard: "Operational Dashboard",
    map: "Live Fleet Map",
    shipments: "Shipments",
    vehicles: "Fleet",
  };

  document.getElementById("page-title").textContent = titles[page] || "Dashboard";

  if (page === "map" && state.map) {
    setTimeout(() => state.map.invalidateSize(), 50);
  }
}

window.showPage = showPage;

function renderDashboard() {
  if (!state.summary) {
    return;
  }

  const k = state.summary.kpis || {};

  document.getElementById("kpi-cards").innerHTML = [
    card("Fleet Vehicles", k.vehicles ?? 0),
    card("Active Shipments", k.active_shipments ?? 0),
    card("Pending Assignment", k.pending_shipments ?? 0),
    card("Delayed > 15 min", k.delayed_shipments ?? 0),
    card("Fleet Utilization", `${k.fleet_utilization_pct ?? 0}%`),
    card("On-Time Rate", `${k.on_time_rate_pct ?? 100}%`),
  ].join("");

  const alerts = state.summary.alerts || [];

  document.getElementById("alerts").innerHTML = alerts.length
    ? alerts
        .map((alertItem) => {
          return `<div class="alert ${escapeHtml(alertItem.severity)}">${escapeHtml(alertItem.message)}</div>`;
        })
        .join("")
    : '<div class="muted">No active alerts.</div>';

  const delayed = state.summary.delayed_shipments || [];

  document.getElementById("delayed-shipments").innerHTML = delayed.length
    ? `<table>
        <thead>
          <tr>
            <th>Tracking</th>
            <th>Customer</th>
            <th>Predicted Delay</th>
          </tr>
        </thead>
        <tbody>
          ${delayed
            .map((item) => {
              return `<tr>
                <td>${escapeHtml(item.tracking_code)}</td>
                <td>${escapeHtml(item.customer)}</td>
                <td>${item.predicted_delay_minutes} min</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`
    : '<div class="muted">No critical delayed shipments.</div>';

  if (typeof Chart !== "undefined") {
    const shipmentEntries = Object.entries(state.summary.shipments_by_status || {});

    if (state.charts.shipments) {
      state.charts.shipments.destroy();
    }

    state.charts.shipments = new Chart(document.getElementById("shipmentsChart"), {
      type: "doughnut",
      data: {
        labels: shipmentEntries.map(([key]) => formatStatus(key)),
        datasets: [
          {
            data: shipmentEntries.map(([, value]) => value),
            backgroundColor: shipmentEntries.map(([key]) => statusColors.shipment[key] || "#94a3b8"),
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            position: "bottom",
          },
        },
      },
    });

    const vehicleEntries = Object.entries(state.summary.vehicles_by_status || {});

    if (state.charts.vehicles) {
      state.charts.vehicles.destroy();
    }

    state.charts.vehicles = new Chart(document.getElementById("vehiclesChart"), {
      type: "bar",
      data: {
        labels: vehicleEntries.map(([key]) => formatStatus(key)),
        datasets: [
          {
            label: "Vehicles",
            data: vehicleEntries.map(([, value]) => value),
            backgroundColor: vehicleEntries.map(([key]) => statusColors.vehicle[key] || "#94a3b8"),
          },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            display: false,
          },
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              precision: 0,
            },
          },
        },
      },
    });
  }
}

function card(label, value, sub = "") {
  return `
    <div class="card kpi">
      <div class="kpi-label">${escapeHtml(label)}</div>
      <div class="kpi-value">${value}</div>
      ${sub ? `<div class="muted">${escapeHtml(sub)}</div>` : ""}
    </div>
  `;
}

function formatStatus(value) {
  return (value || "").replaceAll("_", " ");
}

function statusBadge(statusValue) {
  return `<span class="badge ${escapeHtml(statusValue)}">${escapeHtml(formatStatus(statusValue))}</span>`;
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function renderVehicles() {
  const element = document.getElementById("vehicles-table");

  if (!element) {
    return;
  }

  if (!state.vehicles.length) {
    element.innerHTML = '<div class="muted">No vehicles found.</div>';
    return;
  }

  const rows = state.vehicles
    .map((vehicle) => {
      const activeLoad = state.shipments
        .filter(
          (shipment) =>
            shipment.assigned_vehicle_id === vehicle.id &&
            ["assigned", "in_transit"].includes(shipment.status)
        )
        .reduce((sum, shipment) => sum + (shipment.weight_kg || 0), 0);

      const utilization = vehicle.capacity_kg
        ? Math.round((activeLoad / vehicle.capacity_kg) * 100)
        : 0;

      return `
        <tr>
          <td>${escapeHtml(vehicle.name)}</td>
          <td>${escapeHtml(vehicle.license_plate)}</td>
          <td>${escapeHtml(vehicle.vehicle_type)}</td>
          <td>${vehicle.capacity_kg}</td>
          <td>${activeLoad}</td>
          <td>${utilization}%</td>
          <td>${statusBadge(vehicle.status)}</td>
          <td>${vehicle.speed_kmh || 0} km/h</td>
          <td>${formatDateTime(vehicle.updated_at)}</td>
          <td class="actions">
            <button class="link" onclick="goToVehicleRoute(${vehicle.id})">Route</button>
            <button class="link" onclick="openVehicleModal(${vehicle.id})">Edit</button>
            <button class="link danger" onclick="deleteVehicle(${vehicle.id})">Delete</button>
          </td>
        </tr>
      `;
    })
    .join("");

  element.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Plate</th>
          <th>Type</th>
          <th>Capacity kg</th>
          <th>Active Load kg</th>
          <th>Utilization</th>
          <th>Status</th>
          <th>Speed</th>
          <th>Updated</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

function renderShipments() {
  const element = document.getElementById("shipments-table");

  if (!element) {
    return;
  }

  if (!state.shipments.length) {
    element.innerHTML = '<div class="muted">No shipments found.</div>';
    return;
  }

  const rows = state.shipments
    .map((shipment) => {
      const vehicle = state.vehicles.find((item) => item.id === shipment.assigned_vehicle_id);

      const delayClass =
        (shipment.predicted_delay_minutes || 0) > 15
          ? "badge exception"
          : "badge delivered";

      return `
        <tr>
          <td>${escapeHtml(shipment.tracking_code)}</td>
          <td>${escapeHtml(shipment.customer)}</td>
          <td>${escapeHtml(shipment.origin_name)}</td>
          <td>${escapeHtml(shipment.dest_name)}</td>
          <td>${shipment.weight_kg}</td>
          <td>${escapeHtml(shipment.priority)}</td>
          <td>${statusBadge(shipment.status)}</td>
          <td>${vehicle ? escapeHtml(vehicle.name) : "-"}</td>
          <td>${shipment.eta_minutes || 0} min</td>
          <td><span class="${delayClass}">${shipment.predicted_delay_minutes || 0} min</span></td>
          <td class="actions">
            <button class="link" onclick="openShipmentModal(${shipment.id})">Edit</button>
          </td>
        </tr>
      `;
    })
    .join("");

  element.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Tracking</th>
          <th>Customer</th>
          <th>Origin</th>
          <th>Destination</th>
          <th>Weight kg</th>
          <th>Priority</th>
          <th>Status</th>
          <th>Vehicle</th>
          <th>ETA</th>
          <th>Predicted Delay</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `;
}

function updateMap() {
  if (!state.map || !state.vehicleMarkers || !state.shipmentMarkers) {
    return;
  }

  state.vehicleMarkers.clearLayers();
  state.shipmentMarkers.clearLayers();
  state.routeLayer.clearLayers();

  state.vehicles.forEach((vehicle) => {
    if (vehicle.lat == null || vehicle.lng == null) {
      return;
    }

    const color = statusColors.vehicle[vehicle.status] || "#94a3b8";

    const marker = L.circleMarker([vehicle.lat, vehicle.lng], {
      radius: 8,
      fillColor: color,
      color: "#ffffff",
      weight: 1,
      fillOpacity: 0.95,
    });

    marker.bindPopup(`
      <strong>${escapeHtml(vehicle.name)}</strong><br/>
      ${escapeHtml(vehicle.license_plate)}<br/>
      Status: ${escapeHtml(formatStatus(vehicle.status))}<br/>
      Speed: ${vehicle.speed_kmh || 0} km/h<br/>
      <button onclick="selectVehicleRoute(${vehicle.id})">Optimized Route</button>
    `);

    state.vehicleMarkers.addLayer(marker);
  });

  state.shipments.forEach((shipment) => {
    if (shipment.dest_lat == null || shipment.dest_lng == null) {
      return;
    }

    const color = statusColors.shipment[shipment.status] || "#94a3b8";

    const marker = L.circleMarker([shipment.dest_lat, shipment.dest_lng], {
      radius: 5,
      fillColor: color,
      color: "#ffffff",
      weight: 1,
      fillOpacity: 0.9,
    });

    marker.bindPopup(`
      <strong>${escapeHtml(shipment.tracking_code)}</strong><br/>
      ${escapeHtml(shipment.customer)}<br/>
      Status: ${escapeHtml(formatStatus(shipment.status))}<br/>
      Destination: ${escapeHtml(shipment.dest_name)}
    `);

    state.shipmentMarkers.addLayer(marker);
  });

  if (state.selectedVehicleId) {
    selectVehicleRoute(state.selectedVehicleId, true);
  }
}

window.selectVehicleRoute = async function (vehicleId, silent = false) {
  state.selectedVehicleId = vehicleId;

  try {
    const vehicle = state.vehicles.find((item) => item.id === vehicleId);

    if (!vehicle) {
      throw new Error("Vehicle not loaded");
    }

    const route = await api(`/api/optimization/vehicle/${vehicleId}`);

    state.routeLayer.clearLayers();

    const points = [];

    if (vehicle.lat != null && vehicle.lng != null) {
      points.push([vehicle.lat, vehicle.lng]);
    }

    route.stops.forEach((stop) => {
      points.push([stop.lat, stop.lng]);
    });

    if (points.length > 1) {
      state.routeLayer.addLayer(
        L.polyline(points, {
          color: "#38bdf8",
          weight: 3,
          dashArray: "6,8",
        })
      );
    }

    route.stops.forEach((stop) => {
      const color = stop.action === "pickup" ? "#f59e0b" : "#22c55e";

      const marker = L.circleMarker([stop.lat, stop.lng], {
        radius: 6,
        fillColor: color,
        color: "#ffffff",
        weight: 1,
        fillOpacity: 0.95,
      });

      marker.bindPopup(`
        ${stop.sequence}. ${escapeHtml(stop.label)}<br/>
        Leg: ${stop.distance_km} km<br/>
        ETA: ${stop.eta_minutes} min
      `);

      state.routeLayer.addLayer(marker);
    });

    renderRoutePanel(vehicle, route);
  } catch (error) {
    if (!silent) {
      showToast(error.message, "error");
    }
  }
};

function renderRoutePanel(vehicle, route) {
  const panel = document.getElementById("route-panel");

  if (!panel) {
    return;
  }

  if (!route.stops.length) {
    panel.innerHTML = `
      <h3>Route Intelligence</h3>
      <div class="muted">${escapeHtml(vehicle.name)} has no active stops.</div>
    `;
    return;
  }

  panel.innerHTML = `
    <h3>Route Intelligence</h3>

    <div class="route-summary">
      <div><strong>${escapeHtml(vehicle.name)}</strong></div>
      <div>Total distance: ${route.total_distance_km} km</div>
      <div>Estimated duration: ${route.total_duration_minutes} min</div>
    </div>

    <ol class="route-stops">
      ${route.stops
        .map((stop) => {
          return `
            <li>
              ${escapeHtml(stop.label)}
              <div class="muted">${stop.distance_km} km leg • ETA ${stop.eta_minutes} min</div>
            </li>
          `;
        })
        .join("")}
    </ol>
  `;
}

window.goToVehicleRoute = function (vehicleId) {
  showPage("map");
  window.selectVehicleRoute(vehicleId);
};

window.deleteVehicle = async function (vehicleId) {
  if (!confirm("Delete this vehicle?")) {
    return;
  }

  try {
    await api(`/api/vehicles/${vehicleId}`, {
      method: "DELETE",
    });

    showToast("Vehicle deleted");
    await loadAll();
  } catch (error) {
    showToast(error.message, "error");
  }
};

function openModal() {
  document.getElementById("modal").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
  document.getElementById("modal-body").innerHTML = "";
}

window.closeModal = closeModal;

function vehicleFormHtml(vehicle = {}) {
  const types = ["truck", "van", "car", "reefer"];
  const statuses = ["available", "en_route", "maintenance"];

  return `
    <form id="vehicle-form" class="form-grid">
      <label>Name
        <input name="name" value="${escapeAttr(vehicle.name || "")}" required />
      </label>

      <label>License Plate
        <input name="license_plate" value="${escapeAttr(vehicle.license_plate || "")}" required />
      </label>

      <label>Type
        <select name="vehicle_type">
          ${types
            .map((type) => {
              return `<option value="${type}" ${(vehicle.vehicle_type || "truck") === type ? "selected" : ""}>${type}</option>`;
            })
            .join("")}
        </select>
      </label>

      <label>Capacity kg
        <input name="capacity_kg" type="number" step="0.1" min="1" value="${vehicle.capacity_kg ?? 1000}" required />
      </label>

      <label>Status
        <select name="status">
          ${statuses
            .map((statusValue) => {
              return `<option value="${statusValue}" ${(vehicle.status || "available") === statusValue ? "selected" : ""}>${formatStatus(statusValue)}</option>`;
            })
            .join("")}
        </select>
      </label>

      <label>Speed km/h
        <input name="speed_kmh" type="number" step="0.1" min="0" value="${vehicle.speed_kmh ?? 0}" />
      </label>

      <label>Latitude
        <input name="lat" type="number" step="any" value="${vehicle.lat ?? ""}" />
      </label>

      <label>Longitude
        <input name="lng" type="number" step="any" value="${vehicle.lng ?? ""}" />
      </label>

      <div class="form-actions">
        <button type="button" class="secondary" onclick="closeModal()">Cancel</button>
        <button type="submit" class="primary">Save Vehicle</button>
      </div>
    </form>
  `;
}

window.openVehicleModal = function (vehicleId) {
  const vehicle = vehicleId
    ? state.vehicles.find((item) => item.id === vehicleId)
    : null;

  if (vehicleId && !vehicle) {
    showToast("Vehicle not found", "error");
    return;
  }

  document.getElementById("modal-title").textContent = vehicle
    ? "Edit Vehicle"
    : "New Vehicle";

  document.getElementById("modal-body").innerHTML = vehicleFormHtml(vehicle || {});

  document.getElementById("vehicle-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const formData = new FormData(event.target);

    const payload = {
      name: formData.get("name"),
      license_plate: formData.get("license_plate"),
      vehicle_type: formData.get("vehicle_type"),
      capacity_kg: Number(formData.get("capacity_kg")),
      status: formData.get("status"),
      speed_kmh: Number(formData.get("speed_kmh") || 0),
    };

    const lat = formData.get("lat");
    const lng = formData.get("lng");

    if (lat !== "") {
      payload.lat = Number(lat);
    }

    if (lng !== "") {
      payload.lng = Number(lng);
    }

    try {
      if (vehicle) {
        await api(`/api/vehicles/${vehicle.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await api("/api/vehicles", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }

      closeModal();
      showToast("Vehicle saved");
      await loadAll();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  openModal();
};

function shipmentFormHtml(shipment = {}) {
  const priorities = ["high", "normal", "low"];
  const statuses = ["pending", "assigned", "in_transit", "delivered", "exception"];

  const assignedId = shipment.assigned_vehicle_id || "";

  const vehicleOptions = state.vehicles
    .map((vehicle) => {
      return `<option value="${vehicle.id}" ${vehicle.id === assignedId ? "selected" : ""}>${escapeHtml(vehicle.name)}</option>`;
    })
    .join("");

  return `
    <form id="shipment-form" class="form-grid">
      <label>Tracking Code
        <input name="tracking_code" value="${escapeAttr(shipment.tracking_code || "")}" placeholder="Leave blank to auto-generate" />
      </label>

      <label>Customer
        <input name="customer" value="${escapeAttr(shipment.customer || "")}" required />
      </label>

      <label>Origin Name
        <input name="origin_name" value="${escapeAttr(shipment.origin_name || "")}" required />
      </label>

      <label>Origin Latitude
        <input name="origin_lat" type="number" step="any" value="${shipment.origin_lat ?? ""}" required />
      </label>

      <label>Origin Longitude
        <input name="origin_lng" type="number" step="any" value="${shipment.origin_lng ?? ""}" required />
      </label>

      <label>Destination Name
        <input name="dest_name" value="${escapeAttr(shipment.dest_name || "")}" required />
      </label>

      <label>Destination Latitude
        <input name="dest_lat" type="number" step="any" value="${shipment.dest_lat ?? ""}" required />
      </label>

      <label>Destination Longitude
        <input name="dest_lng" type="number" step="any" value="${shipment.dest_lng ?? ""}" required />
      </label>

      <label>Weight kg
        <input name="weight_kg" type="number" step="0.1" min="0.1" value="${shipment.weight_kg ?? 100}" required />
      </label>

      <label>Priority
        <select name="priority">
          ${priorities
            .map((priority) => {
              return `<option value="${priority}" ${(shipment.priority || "normal") === priority ? "selected" : ""}>${priority}</option>`;
            })
            .join("")}
        </select>
      </label>

      <label>Status
        <select name="status">
          ${statuses
            .map((statusValue) => {
              return `<option value="${statusValue}" ${(shipment.status || "pending") === statusValue ? "selected" : ""}>${formatStatus(statusValue)}</option>`;
            })
            .join("")}
        </select>
      </label>

      <label>Assigned Vehicle
        <select name="assigned_vehicle_id">
          <option value="">Unassigned</option>
          ${vehicleOptions}
        </select>
      </label>

      <div class="form-actions">
        <button type="button" class="secondary" onclick="closeModal()">Cancel</button>
        <button type="submit" class="primary">Save Shipment</button>
      </div>
    </form>
  `;
}

window.openShipmentModal = function (shipmentId) {
  let shipment = shipmentId
    ? state.shipments.find((item) => item.id === shipmentId)
    : null;

  if (shipmentId && !shipment) {
    showToast("Shipment not found", "error");
    return;
  }

  if (!shipment) {
    shipment = {
      priority: "normal",
      status: "pending",
      origin_lat: 41.8781,
      origin_lng: -87.6298,
      dest_lat: 41.885,
      dest_lng: -87.615,
      weight_kg: 100,
    };
  }

  document.getElementById("modal-title").textContent = shipmentId
    ? "Edit Shipment"
    : "New Shipment";

  document.getElementById("modal-body").innerHTML = shipmentFormHtml(shipment);

  document.getElementById("shipment-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const formData = new FormData(event.target);

    const payload = {
      customer: formData.get("customer"),
      origin_name: formData.get("origin_name"),
      origin_lat: Number(formData.get("origin_lat")),
      origin_lng: Number(formData.get("origin_lng")),
      dest_name: formData.get("dest_name"),
      dest_lat: Number(formData.get("dest_lat")),
      dest_lng: Number(formData.get("dest_lng")),
      weight_kg: Number(formData.get("weight_kg")),
      priority: formData.get("priority"),
      status: formData.get("status"),
      assigned_vehicle_id: formData.get("assigned_vehicle_id")
        ? Number(formData.get("assigned_vehicle_id"))
        : null,
    };

    const trackingCode = formData.get("tracking_code");

    if (trackingCode) {
      payload.tracking_code = trackingCode;
    }

    try {
      if (shipmentId) {
        await api(`/api/shipments/${shipmentId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await api("/api/shipments", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }

      closeModal();
      showToast("Shipment saved");
      await loadAll();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  openModal();
};

function showToast(message, type = "success") {
  const toast = document.getElementById("toast");

  if (!toast) {
    return;
  }

  toast.textContent = message;
  toast.className = `toast ${type}`;
  toast.classList.remove("hidden");

  setTimeout(() => {
    toast.classList.add("hidden");
  }, 3500);
}

function escapeHtml(value) {
  if (value === null || value === undefined) {
    return "";
  }

  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
