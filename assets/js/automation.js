(function () {
  "use strict";

  function h(tag, attrs, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") element.className = value;
      else element.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      element.appendChild(typeof child === "object" ? child : document.createTextNode(String(child)));
    }
    return element;
  }

  function currentDateLabel() {
    const parts = new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei", month: "numeric", day: "numeric", weekday: "long",
    }).formatToParts(new Date());
    const value = (type) => parts.find((part) => part.type === type)?.value || "";
    return `${value("month")}月${value("day")}日 ${value("weekday")}`;
  }

  function badge(text, className) {
    return h("span", { class: `automation-badge ${className || ""}` }, text);
  }

  function statusLabel(status) {
    return { success: "成功", error: "失敗", skipped: "略過" }[status] || status || "—";
  }

  function renderJobs(payload) {
    const history = payload.job_history || {};
    const rows = (payload.jobs || []).map((job) => {
      const stateClass = job.status === "error" ? "error" : (job.due_today ? "due" : "pending");
      const stateText = job.status === "success"
        ? (job.changed_modules || []).length ? "已更新" : "已檢查，未變"
        : job.status === "error" ? "失敗" : "今天略過";
      const lastSuccess = (history[job.id] || {}).last_success_at || "—";
      return h("tr", {},
        h("td", {}, h("span", { class: "module-title" }, job.label), h("code", {}, job.id)),
        h("td", {}, (job.module_ids || []).join("、")),
        h("td", {}, job.schedule || "—"),
        h("td", {}, badge(stateText, stateClass), h("span", { class: "policy-reason" }, job.message || "")),
        h("td", {}, lastSuccess));
    });
    document.getElementById("job-rows").replaceChildren(...rows);
  }

  function renderModules(payload) {
    const rows = (payload.modules || []).map((module) => h("tr", {},
      h("td", {},
        h("span", { class: "module-title" }, module.title),
        h("span", { class: "module-id" }, module.id)),
      h("td", {},
        badge(module.mode_label, module.mode),
        h("span", { class: "policy-reason" }, module.reason)),
      h("td", {}, module.cadence || "—"),
      h("td", {}, module.decision || "—"),
      h("td", {}, module.fetched_at || module.updated || "—")));
    document.getElementById("module-rows").replaceChildren(...rows);
  }

  function render(payload) {
    const lastRun = payload.last_run || {};
    const jobs = payload.jobs || [];
    const modules = payload.modules || [];
    const dueCount = jobs.filter((job) => job.due_today).length;
    const pendingCount = modules.filter((module) => module.mode === "pending").length;

    document.getElementById("automation-generated-at").textContent = `狀態產生於 ${payload.generated_at || "—"}`;
    document.getElementById("last-run-status").replaceChildren(
      badge(statusLabel(lastRun.status), lastRun.status || "pending"));
    document.getElementById("last-run-time").textContent = lastRun.finished_at || "—";
    document.getElementById("due-job-count").textContent = dueCount;
    document.getElementById("changed-module-count").textContent = (lastRun.changed_modules || []).length;
    document.getElementById("pending-module-count").textContent = pendingCount;
    document.getElementById("last-run-summary").textContent = lastRun.summary || "尚無執行摘要";
    document.getElementById("log-file-path").textContent = payload.log_file || "—";
    document.getElementById("execution-log").textContent = (payload.log_tail || []).join("\n") || "尚無執行紀錄。";
    renderJobs(payload);
    renderModules(payload);
  }

  document.getElementById("automation-current-date").textContent = currentDateLabel();
  fetch("data/automation-status.json", { cache: "no-cache" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(render)
    .catch((error) => {
      const box = document.getElementById("automation-error");
      box.hidden = false;
      box.textContent = location.protocol === "file:"
        ? "管理頁需要透過 HTTP 開啟。請執行 python3 -m http.server 8000。"
        : `載入 data/automation-status.json 失敗：${error.message}`;
    });
})();
