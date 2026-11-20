"use strict";

window.startTicketBoard = function (fetchWithToken) {
  const $ = (id) => document.getElementById(id);
  const labels = {backlog: "Backlog", ready: "Ready", in_progress: "In progress",
    review: "Review", done: "Done", blocked: "Blocked", needs_human: "Needs human"};
  const legal = {backlog: ["ready"], ready: ["in_progress"], in_progress: ["review", "blocked"],
    review: ["done", "in_progress"], done: [], blocked: [], needs_human: []};
  const lists = ["depends_on", "inputs", "outputs", "acceptance"];
  const metadata = ["id", "attempts", "tokens", "token_cost", "created", "updated"];
  const form = $("ticket-form");
  const training = $("training-form");
  let settings = {agents: {}, dispatch: false};
  let tickets = [];
  let approvals = [];
  let current = null;
  let selectedView = "board";
  let selectedJob = null;
  let stream = null;
  let refreshInProgress = false;

  function el(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  async function api(path, method = "GET", body, signal) {
    const response = await fetchWithToken("api/" + path, {
      method, signal, headers: body === undefined ? {} : {"Content-Type": "application/json"},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = Array.isArray(data.detail)
        ? data.detail.map((item) => item.loc.at(-1) + " — " + item.msg).join(". ") : data.detail;
      throw new Error(detail || ("The request returned HTTP " + response.status + "."));
    }
    return response;
  }

  async function json(path, method, body) {
    return (await api(path, method, body)).json();
  }

  function message(id, text) {
    $(id).textContent = text || "";
    $(id).hidden = !text;
  }

  function action(id, handler, messageId = "notice") {
    $(id).addEventListener("click", async () => {
      message(messageId, "");
      try { await handler(); } catch (error) { message(messageId, error.message); }
    });
  }

  function options(select, values, selected) {
    select.replaceChildren(...values.map(([value, label]) => new Option(label, value)));
    select.value = selected;
  }

  function ticketCard(ticket) {
    const card = el("button", null, "card");
    card.type = "button";
    card.append(el("span", ticket.id + " · " + ticket.type, "card-meta"), el("strong", ticket.title),
      el("span", (ticket.assignee || "Unassigned") + (ticket.active ? " · Agent active" : ""), "card-meta"));
    card.addEventListener("click", () => openTicket(ticket.id).catch((error) => message("notice", error.message)));
    return card;
  }

  function renderBoard() {
    const filter = $("filter").value;
    const search = $("search").value.trim().toLowerCase();
    $("columns").replaceChildren();
    for (const [status, label] of Object.entries(labels)) {
      if (filter && filter !== status) continue;
      const cards = tickets.filter((ticket) => ticket.status === status &&
        [ticket.id, ticket.title, ticket.assignee].some((value) => value?.toLowerCase().includes(search)));
      const column = el("section", null, "column");
      column.dataset.status = status;
      const heading = el("h3", label);
      heading.append(el("span", cards.length));
      const stack = el("div", null, "stack");
      stack.append(...(cards.length ? cards.map(ticketCard) : [el("p", "No tickets", "empty")]));
      column.append(heading, stack);
      $("columns").append(column);
    }
  }

  function renderInbox() {
    const escalated = tickets.filter((ticket) => ticket.status === "needs_human");
    $("inbox-count").textContent = approvals.length + escalated.length || "";
    $("escalated").replaceChildren(...(escalated.length ? escalated.map(ticketCard)
      : [el("p", "No escalated tickets.", "empty")]));
    $("approvals").replaceChildren();
    if (!approvals.length) $("approvals").append(el("p", "No pending tool approvals.", "empty"));
    for (const approval of approvals) {
      const box = el("article", null, "panel");
      box.append(el("h3", approval.name + " · " + approval.ticket_id),
        el("pre", JSON.stringify(approval.arguments, null, 2)));
      const buttons = el("div", null, "actions");
      for (const [label, decision] of [["Deny", "denied"], ["Approve this call", "approved"]]) {
        const button = el("button", label, decision === "approved" ? "primary" : null);
        button.type = "button";
        button.addEventListener("click", async () => {
          buttons.querySelectorAll("button").forEach((item) => {item.disabled = true;});
          try {
            await json("approvals/" + approval.id, "POST", {decision});
            await refresh();
          } catch (error) {
            message("notice", error.message);
            buttons.querySelectorAll("button").forEach((item) => {item.disabled = false;});
          }
        });
        buttons.append(button);
      }
      box.append(buttons);
      $("approvals").append(box);
    }
  }

  async function refresh() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    try {
      const [board, pending] = await Promise.all([json("tickets"), json("approvals")]);
      const boardChanged = JSON.stringify(board) !== JSON.stringify(tickets);
      const inboxChanged = JSON.stringify(pending) !== JSON.stringify(approvals);
      tickets = board;
      approvals = pending;
      if (boardChanged || !$("columns").childElementCount) renderBoard();
      if (boardChanged || inboxChanged || !$("approvals").childElementCount) renderInbox();
    } finally { refreshInProgress = false; }
  }

  function fillEditor(ticket) {
    current = ticket;
    form.reset();
    $("metadata").open = false;
    $("records").querySelectorAll("details").forEach((item) => {item.open = false;});
    $("ticket-reference").textContent = ticket?.id || "Backlog";
    $("editor-heading").textContent = ticket ? "Edit ticket" : "New ticket";
    const assignees = new Set(Object.keys(settings.agents).filter((name) => !["reviewer", "orchestrator"].includes(name)));
    if (ticket?.assignee) assignees.add(ticket.assignee);
    options(form.elements.assignee, [["", "Unassigned"], ...[...assignees].map((name) => [name,
      name + (settings.agents[name]?.enabled ? "" : " (disabled)")])], ticket?.assignee || "");
    const state = ticket?.status || "backlog";
    const statuses = [state, ...legal[state], ...(state === "needs_human" ? [] : ["needs_human"])];
    options(form.elements.status, statuses.map((id) => [id, labels[id]]), state);
    for (const name of ["title", "description", "type", "parent_id", ...metadata]) {
      form.elements[name].value = ticket?.[name] ?? (name === "type" ? "research" : "");
    }
    for (const name of lists) form.elements[name].value = (ticket?.[name] || []).join("\n");
    $("records").hidden = $("metadata").hidden = $("status-control").hidden = !ticket;
    $("triage").hidden = !ticket || ticket.active || ticket.triage_queued ||
      !["backlog", "ready"].includes(state) || !settings.dispatch || !settings.agents.orchestrator?.enabled;
    $("escalate-active").hidden = !ticket?.active || state === "needs_human";
    $("save-ticket").disabled = ticket?.active === true;
    message("editor-message", ticket?.active ? "An agent is working on this ticket. Reload after the run finishes."
      : ticket?.triage_queued ? "Orchestrator triage is queued." : "");
    $("history").replaceChildren(...(ticket?.history || []).slice().reverse().map((event) => {
      const box = el("div", null, "panel");
      box.append(el("strong", event.source ? labels[event.source] + " → " + labels[event.target] : event.kind.replaceAll("_", " ")),
        el("p", new Date(event.at).toLocaleString() + (event.actor ? " · " + event.actor : ""), "card-meta"));
      if (event.reason) box.append(el("p", event.reason));
      return box;
    }));
    $("run-logs").replaceChildren();
  }

  async function openTicket(key, startNew = true) {
    fillEditor(key ? await json("tickets/" + key) : null);
    if (startNew && !$("ticket-dialog").open) $("ticket-dialog").showModal();
  }

  async function loadRuns() {
    if (!current) return;
    const key = current.id;
    const runs = await json("tickets/" + key + "/runs");
    if (current?.id !== key) return;
    $("run-logs").replaceChildren(...(runs.length ? runs.map((run) => {
      const detail = el("details");
      detail.append(el("summary", run.agent + " · " + run.kind + " · " + run.status),
        el("p", new Date(run.started).toLocaleString() + " · " + (run.input_tokens + run.output_tokens)
          + " tokens · $" + run.cost_usd.toFixed(6) + (run.estimated_usage ? " estimated" : ""), "card-meta"),
        el("pre", JSON.stringify(run, null, 2)));
      return detail;
    }) : [el("p", "No runs yet.", "empty")]));
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    for (const key of lists) values[key] = values[key].split("\n").map((line) => line.trim()).filter(Boolean);
    for (const key of ["parent_id", "assignee", "created", "updated"]) values[key] = values[key].trim() || null;
    if (current) {
      for (const key of ["attempts", "tokens", "token_cost"]) values[key] = Number(values[key]);
      values.id = values.id.trim();
      values.revision = current.revision;
    } else {
      for (const key of [...metadata, "status"]) delete values[key];
    }
    $("save-ticket").disabled = true;
    try {
      const saved = current ? await json("tickets/" + current.id, "PUT", values) : await json("tickets", "POST", values);
      $("ticket-dialog").close();
      message("notice", saved.id + " saved.");
      await refresh();
    } catch (error) { message("editor-message", error.message); }
    finally { $("save-ticket").disabled = false; }
  });

  async function datasets() {
    const exporting = await json("datasets");
    const agent = training.elements.agent.value;
    const available = exporting.filter((item) => item.startsWith(agent + "--"));
    const select = training.elements.dataset;
    const chosen = select.value;
    options(select, [["", available.length ? "Choose a dataset" : "No exported datasets"], ...available.map((name) => [name, name])],
      available.includes(chosen) ? chosen : "");
  }

  async function renderJobs() {
    const jobs = await json("training");
    $("jobs").replaceChildren(...(jobs.length ? jobs.map((job) => {
      const card = el("button", null, "card");
      card.type = "button";
      card.append(el("strong", job.agent + " · " + job.base_model),
        el("span", job.status + " · " + new Date(job.created).toLocaleString(), "card-meta"));
      card.addEventListener("click", () => watchJob(job));
      return card;
    }) : [el("p", "No training jobs yet.", "empty")]));
  }

  function showJob(job) {
    $("job-detail").hidden = false;
    $("job-state").textContent = job.status + (job.error ? " · " + job.error : "");
    $("model-output").textContent = job.validate_only ? "Validation run" : job.model_path;
    $("cancel-job").hidden = !["queued", "initializing", "validating", "training"].includes(job.status);
  }

  async function watchJob(job) {
    stream?.abort();
    const controller = new AbortController();
    stream = controller;
    selectedJob = job.id;
    $("training-log").textContent = "";
    showJob(job);
    try {
      const response = await api("training/" + job.id + "/stream", "GET", undefined, controller.signal);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done || stream !== controller) break;
        pending += decoder.decode(chunk.value, {stream: true});
        const lines = pending.split("\n");
        pending = lines.pop();
        for (const line of lines) {
          const item = JSON.parse(line);
          if (item.job) showJob(item.job);
          if (item.log) {
            const log = $("training-log");
            const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 35;
            log.textContent = (log.textContent + item.log).slice(-120000);
            if (atBottom) log.scrollTop = log.scrollHeight;
          }
        }
      }
      if (stream === controller) await renderJobs();
    } catch (error) { if (!controller.signal.aborted) message("notice", error.message); }
  }

  training.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitButtons = training.querySelectorAll("[type=submit]");
    submitButtons.forEach((button) => { button.disabled = true; });
    message("notice", "");
    try {
      const fields = Object.fromEntries(new FormData(training));
      const job = await json("training", "POST", {...fields, validate_only: event.submitter?.value === "validate"});
      watchJob(job);
      await renderJobs();
    } catch (error) { message("notice", error.message); }
    finally { submitButtons.forEach((button) => { button.disabled = false; }); }
  });
  training.elements.agent.addEventListener("change", () => {
    training.elements.base_model.value = settings.agents[training.elements.agent.value]?.training_base_model || "";
    datasets().catch((error) => message("notice", error.message));
  });
  action("export", async () => {
    const result = await json("datasets/" + training.elements.agent.value, "POST");
    await datasets();
    training.elements.dataset.value = result.dataset;
    message("notice", "Exported " + result.rows + " reviewed runs.");
  });
  action("download", async () => {
    const dataset = training.elements.dataset.value;
    if (!dataset) throw new Error("Choose a dataset first.");
    const blob = await (await api("datasets/" + encodeURIComponent(dataset))).blob();
    const url = URL.createObjectURL(blob);
    const link = el("a");
    link.href = url;
    link.download = dataset;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  });
  action("cancel-job", async () => showJob(await json("training/" + selectedJob + "/cancel", "POST")));
  action("new-ticket", () => openTicket(null));
  action("close-editor", () => $("ticket-dialog").close(), "editor-message");
  action("reload-ticket", async () => {
    const logs = $("logs-panel").open;
    await openTicket(current.id, false);
    $("logs-panel").open = logs;
  }, "editor-message");
  action("triage", async () => {
    await json("tickets/" + current.id + "/triage", "POST");
    await openTicket(current.id, false);
    await refresh();
  }, "editor-message");
  action("escalate-active", async () => {
    await json("tickets/" + current.id + "/transition", "POST", {
      status: "needs_human", reason: "A human interrupted the active run.",
    });
    await openTicket(current.id, false);
    await refresh();
  }, "editor-message");
  $("logs-panel").addEventListener("toggle", () => {
    if ($("logs-panel").open) loadRuns().catch((error) => message("editor-message", error.message));
  });
  action("lock", () => location.reload());
  options($("filter"), [["", "All statuses"], ...Object.entries(labels)], "");
  $("filter").addEventListener("change", renderBoard);
  $("search").addEventListener("input", renderBoard);

  const tabs = [...document.querySelectorAll("[data-view]")];
  for (const tab of tabs) tab.addEventListener("click", async () => {
    selectedView = tab.dataset.view;
    message("notice", "");
    for (const item of tabs) {
      const active = item === tab;
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
      $(item.dataset.view).hidden = !active;
    }
    try {
      if (selectedView === "training") await Promise.all([datasets(), renderJobs()]);
      else await refresh();
    } catch (error) { message("notice", error.message); }
  });
  async function initialize() {
    settings = await json("settings");
    const names = Object.keys(settings.agents);
    options(training.elements.agent, names.map((name) => [name, name]), names[0] || "");
    $("dispatch-status").textContent = settings.dispatch
      ? "Dispatcher on · " + names.filter((name) => settings.agents[name].enabled).length + " agents enabled"
      : "Dispatcher off · Manual ticket management";
    await refresh();
  }
  initialize().catch((error) => message("notice", error.message));
  setInterval(() => {
    if (!document.hidden) refresh().catch((error) => message("notice", error.message));
  }, 5000);
};
