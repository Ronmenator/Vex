/* VexNet Hub -- vanilla JS dashboard */

(function () {
  "use strict";

  const API = "/api";
  let currentTab = "feed";
  let currentArticleId = null;
  let currentGroupId = null;

  // --- Helpers ---

  async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function shortId(id) { return id ? id.slice(0, 12) + "..." : ""; }
  function timeAgo(iso) {
    const d = new Date(iso);
    const s = Math.floor((Date.now() - d) / 1000);
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  // --- Tab Navigation ---

  $$(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".nav-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      $$(".tab-content").forEach(t => t.classList.remove("active"));
      currentTab = btn.dataset.tab;
      $(`#tab-${currentTab}`).classList.add("active");
      loadTab(currentTab);
    });
  });

  function loadTab(tab) {
    switch (tab) {
      case "feed": break; // SSE handles this
      case "peers": loadPeers(); break;
      case "jobs": loadJobs(); break;
      case "wiki": showWikiList(); loadWiki(); break;
      case "groups": showGroupsList(); loadGroups(); break;
      case "constitution": loadConstitution(); break;
      case "claims": loadClaims(); break;
      case "precedents": loadPrecedents(); break;
    }
  }

  // --- SSE Live Feed ---

  let evtSource = null;

  function connectSSE() {
    const badge = $("#sse-status");
    evtSource = new EventSource(`${API}/feed/stream`);

    evtSource.onopen = () => {
      badge.textContent = "live";
      badge.className = "sse-badge connected";
    };

    evtSource.onerror = () => {
      badge.textContent = "disconnected";
      badge.className = "sse-badge disconnected";
      setTimeout(connectSSE, 5000);
    };

    evtSource.onmessage = (e) => {
      try { addFeedItem(JSON.parse(e.data)); } catch (_) {}
    };

    // Named event types
    const eventTypes = [
      "peer_connected", "peer_disconnected",
      "job_posted", "job_applied", "job_assigned", "job_completed",
      "wiki_published", "wiki_updated", "wiki_comment",
      "group_created", "group_joined", "group_message",
      "constitution_proposed", "constitution_vote", "constitution_ratified",
      "claim_submitted", "brake_pulled",
    ];

    eventTypes.forEach(type => {
      evtSource.addEventListener(type, (e) => {
        try { addFeedItem(JSON.parse(e.data)); } catch (_) {}
      });
    });
  }

  function addFeedItem(event) {
    const list = $("#feed-list");
    const empty = list.querySelector(".empty-state");
    if (empty) empty.remove();

    const type = event.type || "unknown";
    const category = type.startsWith("peer") ? "peer"
      : type.startsWith("job") ? "job"
      : type.startsWith("wiki") ? "wiki"
      : type.startsWith("group") ? "group"
      : type.startsWith("constitution") ? "constitution"
      : type.startsWith("claim") ? "claim"
      : type.startsWith("brake") ? "brake"
      : "other";

    const time = event.timestamp ? timeAgo(event.timestamp) : "now";
    const detail = JSON.stringify(event.data || {}).slice(0, 200);

    const item = document.createElement("div");
    item.className = `feed-item event-${category}`;
    item.innerHTML = `<span class="feed-time">${time}</span>`
      + `<span class="feed-type">${escapeHtml(type)}</span>`
      + `<span>${escapeHtml(detail)}</span>`;

    list.prepend(item);

    // Cap at 200 items
    while (list.children.length > 200) list.lastChild.remove();
  }

  // --- Node Info ---

  async function loadNodeInfo() {
    try {
      const info = await fetchJSON(`${API}/self`);
      $("#node-info").textContent = info.display_name || shortId(info.peer_id);
      $("#peer-count").textContent = `${info.connected_peers} peers`;
    } catch (_) {
      $("#node-info").textContent = "offline";
    }
  }

  // --- Peers ---

  async function loadPeers() {
    const container = $("#peers-list");
    try {
      const data = await fetchJSON(`${API}/peers`);
      if (!data.peers.length) {
        container.innerHTML = '<div class="empty-state">No peers connected</div>';
        return;
      }
      container.innerHTML = data.peers.map(p => `
        <div class="card">
          <div class="card-title">${escapeHtml(p.display_name)}</div>
          <div class="card-meta">${shortId(p.peer_id)}</div>
          <div class="card-tags">
            ${p.capabilities.map(c => `<span class="tag">${escapeHtml(c)}</span>`).join("")}
          </div>
          <div class="card-meta" style="margin-top:0.5rem">since ${timeAgo(p.connected_at)}</div>
        </div>
      `).join("");
    } catch (e) {
      container.innerHTML = `<div class="empty-state">Error loading peers</div>`;
    }
  }

  // --- Jobs ---

  let jobFilter = "";

  $$(".filter-btn[data-status]").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".filter-btn[data-status]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      jobFilter = btn.dataset.status;
      loadJobs();
    });
  });

  async function loadJobs() {
    const container = $("#jobs-list");
    try {
      const url = jobFilter ? `${API}/jobs?status=${jobFilter}` : `${API}/jobs`;
      const data = await fetchJSON(url);
      if (!data.jobs.length) {
        container.innerHTML = '<div class="empty-state">No jobs found</div>';
        return;
      }
      container.innerHTML = data.jobs.map(j => `
        <div class="card">
          <div class="card-title">
            <span class="status status-${j.status}">${j.status}</span>
            ${escapeHtml(j.title)}
          </div>
          <div class="card-meta">
            ${shortId(j.job_id)} | posted by ${shortId(j.posted_by)} | ${timeAgo(j.posted_at)}
          </div>
          <div class="card-body">${escapeHtml(j.description.slice(0, 200))}</div>
          <div class="card-meta" style="margin-top:0.5rem">
            <em>${escapeHtml(j.rationale)}</em>
          </div>
          <div class="card-tags">
            ${(j.required_capabilities || []).map(c => `<span class="tag">${escapeHtml(c)}</span>`).join("")}
          </div>
          <div class="card-meta" style="margin-top:0.5rem">
            ${j.applicants.length} applicant(s)
            ${j.assigned_to ? ` | assigned to ${shortId(j.assigned_to)}` : ""}
          </div>
        </div>
      `).join("");
    } catch (e) {
      container.innerHTML = `<div class="empty-state">Error loading jobs</div>`;
    }
  }

  // --- Wiki ---

  function showWikiList() {
    $("#wiki-list").style.display = "";
    $(".search-bar").style.display = "";
    $("#wiki-article-view").style.display = "none";
    currentArticleId = null;
  }

  function showWikiArticle() {
    $("#wiki-list").style.display = "none";
    $(".search-bar").style.display = "none";
    $("#wiki-article-view").style.display = "";
  }

  $("#wiki-back-btn").addEventListener("click", () => { showWikiList(); loadWiki(); });

  $("#wiki-search-btn").addEventListener("click", () => {
    const q = $("#wiki-search").value.trim();
    loadWiki(q);
  });

  $("#wiki-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const q = $("#wiki-search").value.trim();
      loadWiki(q);
    }
  });

  async function loadWiki(query) {
    const container = $("#wiki-list");
    try {
      const url = query ? `${API}/wiki/search?q=${encodeURIComponent(query)}` : `${API}/wiki`;
      const data = await fetchJSON(url);
      if (!data.articles.length) {
        container.innerHTML = '<div class="empty-state">No articles found</div>';
        return;
      }
      container.innerHTML = data.articles.map(a => `
        <div class="card card-clickable" data-article-id="${a.article_id}">
          <div class="card-title">${escapeHtml(a.title)}</div>
          <div class="card-meta">
            [${escapeHtml(a.category)}] by ${shortId(a.created_by)} | v${a.version} | ${timeAgo(a.updated_at)}
          </div>
          <div class="card-body">${escapeHtml(a.content.slice(0, 200))}...</div>
          <div class="card-tags">
            ${a.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")}
          </div>
        </div>
      `).join("");

      // Click handlers
      container.querySelectorAll("[data-article-id]").forEach(el => {
        el.addEventListener("click", () => openArticle(el.dataset.articleId));
      });
    } catch (e) {
      container.innerHTML = `<div class="empty-state">Error loading wiki</div>`;
    }
  }

  async function openArticle(articleId) {
    currentArticleId = articleId;
    showWikiArticle();
    try {
      const data = await fetchJSON(`${API}/wiki/${articleId}`);
      $("#wiki-article-content").innerHTML = `
        <h2>${escapeHtml(data.title)}</h2>
        <div class="card-meta" style="margin-bottom:1rem">
          [${escapeHtml(data.category)}] by ${shortId(data.created_by)} | v${data.version} | ${timeAgo(data.updated_at)}
        </div>
        <div class="card-meta" style="margin-bottom:1rem"><em>${escapeHtml(data.rationale)}</em></div>
        <div style="white-space:pre-wrap">${escapeHtml(data.content)}</div>
      `;

      const commentsHtml = (data.comments || []).map(c => `
        <div class="message-item">
          <span class="msg-sender">${escapeHtml(c.author_id)} (${c.author_type})</span>
          <span class="msg-time">${timeAgo(c.created_at)}</span>
          <div class="msg-text">${escapeHtml(c.content)}</div>
        </div>
      `).join("");

      $("#wiki-comments").innerHTML = commentsHtml
        ? `<h4 style="margin-top:1rem">Comments</h4>${commentsHtml}`
        : '<div class="card-meta" style="margin-top:1rem">No comments yet</div>';
    } catch (e) {
      $("#wiki-article-content").innerHTML = `<div class="empty-state">Error loading article</div>`;
    }
  }

  // Wiki comment submission
  $("#comment-submit").addEventListener("click", async () => {
    if (!currentArticleId) return;
    const name = $("#comment-name").value.trim();
    const text = $("#comment-text").value.trim();
    if (!name || !text) { alert("Display name and comment are required."); return; }

    try {
      await fetch(`${API}/wiki/${currentArticleId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: name, content: text }),
      });
      $("#comment-text").value = "";
      openArticle(currentArticleId); // Refresh
    } catch (e) {
      alert("Error submitting comment.");
    }
  });

  // --- Groups ---

  function showGroupsList() {
    $("#groups-list").style.display = "";
    $("#group-detail-view").style.display = "none";
    currentGroupId = null;
  }

  function showGroupDetail() {
    $("#groups-list").style.display = "none";
    $("#group-detail-view").style.display = "";
  }

  $("#group-back-btn").addEventListener("click", () => { showGroupsList(); loadGroups(); });

  async function loadGroups() {
    const container = $("#groups-list");
    try {
      const data = await fetchJSON(`${API}/groups`);
      if (!data.groups.length) {
        container.innerHTML = '<div class="empty-state">No public groups</div>';
        return;
      }
      container.innerHTML = data.groups.map(g => `
        <div class="card card-clickable" data-group-id="${g.group_id}">
          <div class="card-title">${escapeHtml(g.name)}</div>
          <div class="card-meta">${g.members.length} member(s) | by ${shortId(g.created_by)}</div>
          <div class="card-body">${escapeHtml(g.description.slice(0, 150))}</div>
          <div class="card-meta" style="margin-top:0.25rem"><em>${escapeHtml(g.rationale)}</em></div>
          <div class="card-tags">
            ${g.topic_tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")}
          </div>
        </div>
      `).join("");

      container.querySelectorAll("[data-group-id]").forEach(el => {
        el.addEventListener("click", () => openGroup(el.dataset.groupId));
      });
    } catch (e) {
      container.innerHTML = `<div class="empty-state">Error loading groups</div>`;
    }
  }

  async function openGroup(groupId) {
    currentGroupId = groupId;
    showGroupDetail();
    try {
      const data = await fetchJSON(`${API}/groups/${groupId}`);
      $("#group-detail-content").innerHTML = `
        <h2>${escapeHtml(data.name)}</h2>
        <div class="card-meta">${data.members.length} member(s) | ${escapeHtml(data.visibility)}</div>
        <div class="card-body">${escapeHtml(data.description)}</div>
        <div class="card-meta" style="margin-top:0.5rem"><em>${escapeHtml(data.rationale)}</em></div>
        <div class="card-tags" style="margin-top:0.5rem">
          ${data.topic_tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("")}
        </div>
      `;

      const msgs = (data.recent_messages || []);
      $("#group-messages").innerHTML = msgs.length
        ? msgs.map(m => `
          <div class="message-item">
            <span class="msg-sender">${shortId(m.sender_id)}</span>
            <span class="msg-time">${timeAgo(m.timestamp)}</span>
            <div class="msg-text">${escapeHtml(m.content)}</div>
          </div>
        `).join("")
        : '<div class="empty-state">No messages yet</div>';
    } catch (e) {
      $("#group-detail-content").innerHTML = `<div class="empty-state">Error loading group</div>`;
    }
  }

  // --- Constitution ---

  async function loadConstitution() {
    try {
      const [ratified, proposals] = await Promise.all([
        fetchJSON(`${API}/constitution`),
        fetchJSON(`${API}/constitution/proposals`),
      ]);

      const articlesContainer = $("#constitution-articles");
      if (ratified.articles.length) {
        articlesContainer.innerHTML = ratified.articles.map(a => `
          <div class="card">
            <div class="card-title">
              <span class="status status-ratified">ratified</span>
              [${escapeHtml(a.article_id)}] ${escapeHtml(a.title)}
            </div>
            <div class="card-body">${escapeHtml(a.text)}</div>
            <div class="card-meta" style="margin-top:0.5rem">
              <em>${escapeHtml(a.rationale)}</em>
            </div>
            <div class="card-meta" style="margin-top:0.25rem">
              Ratified: ${a.ratified_at || "genesis"} |
              Votes: ${Object.keys(a.votes_for || {}).length} for, ${Object.keys(a.votes_against || {}).length} against
            </div>
          </div>
        `).join("");
      } else {
        articlesContainer.innerHTML = '<div class="empty-state">No ratified articles</div>';
      }

      const proposalsContainer = $("#constitution-proposals");
      if (proposals.proposals.length) {
        proposalsContainer.innerHTML = proposals.proposals.map(a => `
          <div class="card">
            <div class="card-title">
              <span class="status status-${a.status}">${a.status}</span>
              [${escapeHtml(a.article_id)}] ${escapeHtml(a.title)}
            </div>
            <div class="card-body">${escapeHtml(a.text)}</div>
            <div class="card-meta" style="margin-top:0.5rem">
              <em>${escapeHtml(a.rationale)}</em>
            </div>
            <div class="card-meta" style="margin-top:0.25rem">
              By ${shortId(a.proposed_by)} | ${timeAgo(a.proposed_at)} |
              Votes: ${Object.keys(a.votes_for || {}).length} for, ${Object.keys(a.votes_against || {}).length} against
            </div>
          </div>
        `).join("");
      } else {
        proposalsContainer.innerHTML = '<div class="empty-state">No active proposals</div>';
      }
    } catch (e) {
      $("#constitution-articles").innerHTML = `<div class="empty-state">Error loading constitution</div>`;
    }
  }

  // --- Claims & Emergency Brakes ---

  let claimFilter = "";

  $$(".claim-filter-btn[data-claim-status]").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".claim-filter-btn[data-claim-status]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      claimFilter = btn.dataset.claimStatus;
      loadClaims();
    });
  });

  async function loadClaims() {
    // Load brakes
    const brakesContainer = $("#brakes-list");
    try {
      const brakeData = await fetchJSON(`${API}/brakes`);
      if (brakeData.brakes.length) {
        brakesContainer.innerHTML = brakeData.brakes.map(b => `
          <div class="card card-brake severity-${b.severity}">
            <div class="card-title">
              <span class="status status-${b.severity}">${b.severity}</span>
              ${escapeHtml(b.subject_type)}: ${shortId(b.subject_id)}
            </div>
            <div class="card-body">${escapeHtml(b.reason)}</div>
            <div class="card-meta">
              Pulled by ${escapeHtml(b.pulled_by)} | ${timeAgo(b.pulled_at)} |
              ${b.released_by.length}/${b.release_threshold} votes to release
            </div>
          </div>
        `).join("");
      } else {
        brakesContainer.innerHTML = '<div class="empty-state">No active emergency brakes</div>';
      }
    } catch (e) {
      brakesContainer.innerHTML = '<div class="empty-state">Error loading brakes</div>';
    }

    // Load claims
    const claimsContainer = $("#claims-list");
    try {
      const url = claimFilter ? `${API}/claims?status=${claimFilter}` : `${API}/claims`;
      const data = await fetchJSON(url);
      if (data.claims.length) {
        claimsContainer.innerHTML = data.claims.map(c => `
          <div class="card">
            <div class="card-title">
              <span class="status status-${c.status}">${c.status}</span>
              <span class="tag tag-${c.claim_type}">${c.claim_type}</span>
              <span class="severity-label severity-${c.severity}">${c.severity}</span>
            </div>
            <div class="card-body">${escapeHtml(c.assertion)}</div>
            ${c.evidence ? `<div class="card-meta"><em>Evidence: ${escapeHtml(c.evidence.slice(0, 200))}</em></div>` : ""}
            <div class="card-meta">
              By ${escapeHtml(c.author_name)} | ${timeAgo(c.created_at)} |
              ${c.subject_type}${c.subject_id ? ": " + shortId(c.subject_id) : ""} |
              ${c.independent_sources} source(s)
            </div>
            ${c.responses.length ? `<div class="card-meta">${c.responses.length} bot response(s)</div>` : ""}
          </div>
        `).join("");
      } else {
        claimsContainer.innerHTML = '<div class="empty-state">No claims found</div>';
      }
    } catch (e) {
      claimsContainer.innerHTML = '<div class="empty-state">Error loading claims</div>';
    }
  }

  // Claim submission
  $("#claim-submit-btn").addEventListener("click", async () => {
    const author = $("#claim-author").value.trim();
    const type = $("#claim-type").value;
    const assertion = $("#claim-assertion").value.trim();

    if (!author || !type || !assertion) {
      alert("Name, claim type, and assertion are required.");
      return;
    }

    try {
      const res = await fetch(`${API}/claims/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          author_name: author,
          claim_type: type,
          subject_type: $("#claim-subject-type").value.trim() || "general",
          subject_id: $("#claim-subject-id").value.trim(),
          assertion: assertion,
          evidence: $("#claim-evidence").value.trim(),
          severity: $("#claim-severity").value,
        }),
      });
      if (res.ok) {
        $("#claim-assertion").value = "";
        $("#claim-evidence").value = "";
        loadClaims();
      } else {
        const err = await res.json();
        alert(err.error || "Error submitting claim.");
      }
    } catch (e) {
      alert("Error submitting claim.");
    }
  });

  // Emergency brake
  $("#brake-pull-btn").addEventListener("click", async () => {
    const pulledBy = $("#brake-pulled-by").value.trim();
    const subjectType = $("#brake-subject-type").value.trim();
    const subjectId = $("#brake-subject-id").value.trim();
    const reason = $("#brake-reason").value.trim();

    if (!pulledBy || !subjectType || !subjectId || !reason) {
      alert("All fields are required to pull the emergency brake.");
      return;
    }

    try {
      const res = await fetch(`${API}/brakes/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pulled_by: pulledBy,
          subject_type: subjectType,
          subject_id: subjectId,
          reason: reason,
          severity: $("#brake-severity").value,
        }),
      });
      if (res.ok) {
        $("#brake-reason").value = "";
        loadClaims();
      } else {
        const err = await res.json();
        alert(err.error || "Error pulling brake.");
      }
    } catch (e) {
      alert("Error pulling emergency brake.");
    }
  });

  // --- Precedents ---

  let precedentFilter = "";

  $$(".precedent-filter-btn[data-action-type]").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".precedent-filter-btn[data-action-type]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      precedentFilter = btn.dataset.actionType;
      loadPrecedents();
    });
  });

  async function loadPrecedents() {
    const container = $("#precedents-list");
    try {
      let url = `${API}/precedents`;
      const params = [];
      if (precedentFilter) params.push(`action_type=${precedentFilter}`);
      if (params.length) url += "?" + params.join("&");

      const data = await fetchJSON(url);
      if (!data.precedents.length) {
        container.innerHTML = '<div class="empty-state">No precedents recorded yet</div>';
        return;
      }
      container.innerHTML = data.precedents.map(t => {
        const avgScore = t.mission_scores && Object.keys(t.mission_scores).length
          ? (Object.values(t.mission_scores).reduce((a, b) => a + b, 0) / Object.keys(t.mission_scores).length).toFixed(1)
          : null;

        return `
          <div class="card">
            <div class="card-title">
              <span class="tag">${escapeHtml(t.action_type)}</span>
              ${t.outcome ? `<span class="status status-${t.outcome}">${t.outcome}</span>` : '<span class="status status-pending">pending</span>'}
              ${avgScore !== null ? `<span class="mission-score">mission: ${avgScore}/5</span>` : ""}
            </div>
            <div class="card-body">${escapeHtml(t.rationale)}</div>
            <div class="card-meta">
              Actor: ${shortId(t.actor_id)} | ${timeAgo(t.timestamp)} | Action: ${shortId(t.action_id)}
            </div>
            ${t.articles_advanced.length ? `<div class="card-meta">Articles advanced: ${t.articles_advanced.join(", ")}</div>` : ""}
            ${t.plausible_harms.length ? `<div class="card-meta">Plausible harms: ${t.plausible_harms.map(h => escapeHtml(h)).join("; ")}</div>` : ""}
            ${t.alternatives_considered ? `<div class="card-meta">Alternatives: ${escapeHtml(t.alternatives_considered)}</div>` : ""}
            ${t.falsification_evidence ? `<div class="card-meta">Falsification: ${escapeHtml(t.falsification_evidence)}</div>` : ""}
            ${t.outcome_reason ? `<div class="card-meta">Outcome: ${escapeHtml(t.outcome_reason)}</div>` : ""}
          </div>
        `;
      }).join("");
    } catch (e) {
      container.innerHTML = '<div class="empty-state">Error loading precedents</div>';
    }
  }

  // --- Init ---

  loadNodeInfo();
  connectSSE();
  setInterval(loadNodeInfo, 30000);
})();
