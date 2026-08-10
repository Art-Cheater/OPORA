(() => {
  const app = document.getElementById("messengerApp");
  if (!app) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const currentUserId = app.dataset.currentUserId;

  const conversationList = document.getElementById("conversationList");
  const userList = document.getElementById("userList");
  const searchResults = document.getElementById("searchResults");
  const globalSearch = document.getElementById("globalSearch");
  const chatsPanel = document.getElementById("chatsPanel");
  const usersPanel = document.getElementById("usersPanel");
  const searchPanel = document.getElementById("searchPanel");
  const emptyState = document.getElementById("emptyState");
  const chatView = document.getElementById("chatView");
  const messagesContainer = document.getElementById("messagesContainer");
  const messageInput = document.getElementById("messageInput");
  const sendBtn = document.getElementById("sendBtn");
  const fileInput = document.getElementById("fileInput");
  const chatPeerName = document.getElementById("chatPeerName");
  const chatPeerStatus = document.getElementById("chatPeerStatus");
  const chatPeerAvatar = document.getElementById("chatPeerAvatar");
  const chatBackBtn = document.getElementById("chatBackBtn");

  let activeConversationId = null;
  let activePeer = null;
  let lastMessageId = null;
  let pollTimer = null;
  let heartbeatTimer = null;
  let searchTimer = null;
  let unreadEtag = null;
  let eventSource = null;
  const pollIntervalMs = Number(app.dataset.pollInterval || 8000);
  const unreadIntervalMs = Number(app.dataset.unreadInterval || 45000);

  function api(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;
    return fetch(url, { ...options, headers });
  }

  function formatTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
      return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function renderAvatar(el, user, online = false) {
    el.textContent = user.initial || "?";
    el.classList.toggle("tg-avatar--online", online);
  }

  function showPanel(name) {
    chatsPanel.classList.toggle("d-none", name !== "chats");
    usersPanel.classList.toggle("d-none", name !== "users");
    searchPanel.classList.toggle("d-none", name !== "search");
    document.querySelectorAll(".tg-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.tab === name);
    });
  }

  function renderConversationItem(conv) {
    const item = document.createElement("div");
    item.className = "tg-list-item";
    item.dataset.conversationId = conv.id;
    if (conv.id === activeConversationId) item.classList.add("active");

    const avatar = document.createElement("div");
    avatar.className = "tg-avatar tg-avatar--sm";
    if (conv.peer.is_online) avatar.classList.add("tg-avatar--online");
    avatar.textContent = conv.peer.initial;

    const body = document.createElement("div");
    body.className = "tg-list-item__body";
    body.innerHTML = `
      <div class="tg-list-item__top">
        <span class="tg-list-item__name">${escapeHtml(conv.peer.full_name)}</span>
        <span class="tg-list-item__time">${formatTime(conv.last_message_at)}</span>
      </div>
      <div class="tg-list-item__top">
        <span class="tg-list-item__preview">${escapeHtml(conv.last_message_preview || "Нет сообщений")}</span>
        ${conv.unread_count ? `<span class="tg-badge">${conv.unread_count}</span>` : ""}
      </div>
    `;

    item.appendChild(avatar);
    item.appendChild(body);
    item.addEventListener("click", () => openConversation(conv.id, conv.peer));
    return item;
  }

  function renderUserItem(user) {
    const item = document.createElement("div");
    item.className = "tg-list-item";
    const avatar = document.createElement("div");
    avatar.className = "tg-avatar tg-avatar--sm";
    if (user.is_online) avatar.classList.add("tg-avatar--online");
    avatar.textContent = user.initial;

    const body = document.createElement("div");
    body.className = "tg-list-item__body";
    body.innerHTML = `
      <div class="tg-list-item__name">${escapeHtml(user.full_name)}</div>
      <div class="tg-list-item__preview">${escapeHtml(
        [user.position, user.department].filter(Boolean).join(" · ") || user.email
      )}${user.is_blocked ? ' <span class="text-danger">(заблокирован)</span>' : ""}${
        !user.is_active ? ' <span class="text-muted">(неактивен)</span>' : ""
      }</div>
    `;

    item.appendChild(avatar);
    item.appendChild(body);
    item.addEventListener("click", () => startChatWithUser(user.id));
    return item;
  }

  async function loadConversations() {
    const res = await api("/messenger/api/conversations");
    if (!res.ok) return;
    const data = await res.json();
    conversationList.innerHTML = "";
    if (!data.conversations.length) {
      conversationList.innerHTML = '<div class="tg-list-empty">Нет диалогов. Начните переписку во вкладке «Контакты».</div>';
      return;
    }
    data.conversations.forEach((conv) => {
      conversationList.appendChild(renderConversationItem(conv));
    });
    updateGlobalUnread(data.total_unread);
  }

  async function loadUsers(query = "") {
    const res = await api(`/messenger/api/users?q=${encodeURIComponent(query)}`);
    if (!res.ok) return;
    const data = await res.json();
    userList.innerHTML = "";
    if (!data.users.length) {
      userList.innerHTML = '<div class="tg-list-empty">Сотрудники не найдены</div>';
      return;
    }
    data.users.forEach((user) => userList.appendChild(renderUserItem(user)));
  }

  async function startChatWithUser(peerId) {
    const res = await api(`/messenger/api/conversations/open/${peerId}`, { method: "POST" });
    if (!res.ok) return;
    const conv = await res.json();
    showPanel("chats");
    await loadConversations();
    await openConversation(conv.id, conv.peer);
  }

  async function openConversation(conversationId, peer) {
    activeConversationId = conversationId;
    activePeer = peer;
    lastMessageId = null;

    emptyState.classList.add("d-none");
    chatView.classList.remove("d-none");
    app.classList.add("chat-open");

    chatPeerName.textContent = peer.full_name;
    chatPeerStatus.textContent = peer.is_online ? "в сети" : "был(а) недавно";
    chatPeerStatus.classList.toggle("online", peer.is_online);
    renderAvatar(chatPeerAvatar, peer, peer.is_online);

    document.querySelectorAll(".tg-list-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.conversationId === conversationId);
    });

    await loadMessages(true);
    startPolling();
  }

  function renderMessage(msg) {
    const wrap = document.createElement("div");
    wrap.className = `tg-msg ${msg.is_mine ? "tg-msg--out" : "tg-msg--in"}`;
    wrap.dataset.messageId = msg.id;

    const bubble = document.createElement("div");
    bubble.className = "tg-bubble";

    if (msg.has_attachment && msg.file) {
      const link = document.createElement("a");
      link.className = "tg-file-link";
      link.href = msg.file.url;
      link.target = "_blank";
      link.innerHTML = `<i class="bi bi-paperclip"></i> ${escapeHtml(msg.file.name)}`;
      bubble.appendChild(link);
      if (msg.body) {
        const text = document.createElement("div");
        text.className = "mt-2";
        text.textContent = msg.body;
        bubble.appendChild(text);
      }
    } else {
      bubble.textContent = msg.body || "";
    }

    const meta = document.createElement("div");
    meta.className = "tg-bubble__meta";
    meta.innerHTML = `
      <span>${formatTime(msg.created_at)}</span>
      ${msg.is_mine ? `<span class="tg-bubble__read">${msg.is_read ? "✓✓" : "✓"}</span>` : ""}
    `;
    bubble.appendChild(meta);
    wrap.appendChild(bubble);
    return wrap;
  }

  async function loadMessages(scrollBottom = false) {
    if (!activeConversationId) return;
    const res = await api(`/messenger/api/conversations/${activeConversationId}/messages`);
    if (!res.ok) return;
    const data = await res.json();

    if (data.conversation?.peer) {
      activePeer = data.conversation.peer;
      chatPeerStatus.textContent = activePeer.is_online ? "в сети" : "был(а) недавно";
      chatPeerStatus.classList.toggle("online", activePeer.is_online);
      renderAvatar(chatPeerAvatar, activePeer, activePeer.is_online);
    }

    const existingIds = new Set(
      [...messagesContainer.querySelectorAll(".tg-msg")].map((el) => el.dataset.messageId)
    );
    const isInitial = existingIds.size === 0;

    data.messages.forEach((msg) => {
      if (!existingIds.has(msg.id)) {
        messagesContainer.appendChild(renderMessage(msg));
        lastMessageId = msg.id;
      }
    });

    if (scrollBottom || isInitial) {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    await loadConversations();
    updateGlobalUnread();
  }

  async function sendMessage() {
    const body = messageInput.value.trim();
    if (!body || !activeConversationId) return;
    sendBtn.disabled = true;
    const res = await api(`/messenger/api/conversations/${activeConversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ body }),
    });
    sendBtn.disabled = false;
    if (!res.ok) return;
    messageInput.value = "";
    messageInput.style.height = "auto";
    const data = await res.json();
    messagesContainer.appendChild(renderMessage(data.message));
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    await loadConversations();
  }

  async function sendFile(file) {
    if (!file || !activeConversationId) return;
    const form = new FormData();
    form.append("file", file);
    const res = await api(`/messenger/api/conversations/${activeConversationId}/attachments`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) return;
    const data = await res.json();
    messagesContainer.appendChild(renderMessage(data.message));
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    await loadConversations();
  }

  async function sendFiles(fileList) {
    const files = Array.from(fileList || []).filter(Boolean);
    for (const file of files) {
      await sendFile(file);
    }
  }

  async function searchMessages(query) {
    if (query.length < 2) {
      showPanel(document.querySelector(".tg-tab.active")?.dataset.tab || "chats");
      return;
    }
    showPanel("search");
    const res = await api(`/messenger/api/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) return;
    const data = await res.json();
    searchResults.innerHTML = "";
    if (!data.results.length) {
      searchResults.innerHTML = '<div class="tg-list-empty">Сообщения не найдены</div>';
      return;
    }
    data.results.forEach((item) => {
      const row = document.createElement("div");
      row.className = "tg-search-result";
      row.innerHTML = `
        <div class="tg-search-result__peer">${escapeHtml(item.peer.full_name)}</div>
        <div class="tg-search-result__text">${escapeHtml(item.message.body || item.message.file?.name || "")}</div>
      `;
      row.addEventListener("click", () => openConversation(item.conversation_id, item.peer));
      searchResults.appendChild(row);
    });
  }

  async function heartbeat() {
    await api("/messenger/api/heartbeat", { method: "POST" });
  }

  async function updateGlobalUnread(count) {
    let total = count;
    if (total === undefined) {
      const headers = {};
      if (unreadEtag) headers["If-None-Match"] = unreadEtag;
      const res = await api("/messenger/api/unread-count", { headers });
      if (res.status === 304) return;
      if (res.ok) {
        unreadEtag = res.headers.get("ETag") || unreadEtag;
        const data = await res.json();
        total = data.total;
      }
    }
    const badge = document.getElementById("messengerUnreadBadge");
    if (!badge) return;
    if (total > 0) {
      badge.textContent = total > 99 ? "99+" : String(total);
      badge.classList.remove("d-none");
    } else {
      badge.classList.add("d-none");
    }
  }

  function startPolling() {
    clearInterval(pollTimer);
    const tick = () => {
      if (document.hidden) return;
      loadMessages(false);
    };
    pollTimer = setInterval(tick, pollIntervalMs);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  function startUnreadStream() {
    if (eventSource || typeof EventSource === "undefined") return;
    try {
      eventSource = new EventSource("/messenger/api/events");
      eventSource.addEventListener("unread", (ev) => {
        try {
          const data = JSON.parse(ev.data || "{}");
          if (typeof data.total === "number") updateGlobalUnread(data.total);
        } catch {
          /* ignore */
        }
      });
      eventSource.onerror = () => {
        eventSource?.close();
        eventSource = null;
      };
    } catch {
      eventSource = null;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && activeConversationId) {
      loadMessages(false);
    }
  });

  document.querySelectorAll(".tg-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      globalSearch.value = "";
      showPanel(tab.dataset.tab);
      if (tab.dataset.tab === "users") loadUsers();
      if (tab.dataset.tab === "chats") loadConversations();
    });
  });

  globalSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = globalSearch.value.trim();
    searchTimer = setTimeout(() => {
      if (q) {
        searchMessages(q);
        loadUsers(q);
      } else {
        showPanel(document.querySelector(".tg-tab.active")?.dataset.tab || "chats");
      }
    }, 300);
  });

  sendBtn.addEventListener("click", sendMessage);
  messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  messageInput.addEventListener("input", () => {
    messageInput.style.height = "auto";
    messageInput.style.height = `${Math.min(messageInput.scrollHeight, 120)}px`;
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files?.length) {
      sendFiles(fileInput.files);
      fileInput.value = "";
    }
  });

  chatBackBtn?.addEventListener("click", () => {
    app.classList.remove("chat-open");
    chatView.classList.add("d-none");
    emptyState.classList.remove("d-none");
    activeConversationId = null;
    stopPolling();
  });

  heartbeat();
  heartbeatTimer = setInterval(heartbeat, 30000);
  loadConversations();
  loadUsers();
  updateGlobalUnread();
  startUnreadStream();

  window.addEventListener("beforeunload", () => {
    clearInterval(pollTimer);
    clearInterval(heartbeatTimer);
    eventSource?.close();
  });
})();
