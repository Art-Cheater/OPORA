(() => {
  const app = document.getElementById("messengerApp");
  if (!app) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const currentUserName = app.dataset.currentUserName || "Вы";

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
  const replyBar = document.getElementById("replyBar");
  const replyBarLabel = document.getElementById("replyBarLabel");
  const replyBarText = document.getElementById("replyBarText");
  const replyBarClose = document.getElementById("replyBarClose");
  const attachPreview = document.getElementById("attachPreview");
  const imageLightbox = document.getElementById("imageLightbox");
  const lightboxImage = document.getElementById("lightboxImage");
  const lightboxClose = document.getElementById("lightboxClose");

  let activeConversationId = null;
  let activePeer = null;
  let lastMessageId = null;
  let pollTimer = null;
  let heartbeatTimer = null;
  let searchTimer = null;
  let unreadEtag = null;
  let replyTarget = null;
  let pendingFiles = [];
  let knownUnreadTotal = null;
  let unreadPollTimer = null;
  const drafts = new Map();
  const pollIntervalMs = Number(app.dataset.pollInterval || 8000);
  const unreadIntervalMs = Number(app.dataset.unreadInterval || 15000);
  const notify = window.OporaMessengerNotify;

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

  function formatPresence(user) {
    if (!user) return "офлайн";
    if (user.is_online) return "в сети";
    if (!user.last_seen_at) return "офлайн";
    const d = new Date(user.last_seen_at);
    if (Number.isNaN(d.getTime())) return "офлайн";
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return `был(а) в ${time}`;
    if (d.toDateString() === yesterday.toDateString()) return `был(а) вчера в ${time}`;
    const date = d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
    return `был(а) ${date} в ${time}`;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text || "";
    return div.innerHTML;
  }

  function isNearBottom(el, threshold = 80) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
  }

  function scrollMessagesToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function renderAvatar(el, user, online = false) {
    el.textContent = user.initial || "?";
    el.classList.toggle("tg-avatar--online", online);
  }

  function updatePeerStatus(peer) {
    if (!peer) return;
    chatPeerStatus.textContent = formatPresence(peer);
    chatPeerStatus.classList.toggle("online", !!peer.is_online);
    renderAvatar(chatPeerAvatar, peer, !!peer.is_online);
  }

  function showPanel(name) {
    chatsPanel.classList.toggle("d-none", name !== "chats");
    usersPanel.classList.toggle("d-none", name !== "users");
    searchPanel.classList.toggle("d-none", name !== "search");
    document.querySelectorAll(".tg-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.tab === name);
    });
  }

  function saveDraft() {
    if (!activeConversationId) return;
    drafts.set(activeConversationId, {
      text: messageInput.value,
      reply: replyTarget,
    });
  }

  function restoreDraft(conversationId) {
    const draft = drafts.get(conversationId);
    messageInput.value = draft?.text || "";
    messageInput.style.height = "auto";
    if (messageInput.value) {
      messageInput.style.height = `${Math.min(messageInput.scrollHeight, 120)}px`;
    }
    if (draft?.reply) {
      setReplyTarget(draft.reply);
    } else {
      clearReplyTarget();
    }
  }

  function clearComposerState() {
    messageInput.value = "";
    messageInput.style.height = "auto";
    clearReplyTarget();
    clearPendingFiles();
  }

  function setReplyTarget(msg) {
    replyTarget = {
      id: msg.id,
      body: msg.body || msg.file?.name || msg.replyPreview || "",
      is_mine: !!msg.is_mine,
      sender_name: msg.is_mine
        ? currentUserName
        : msg.sender_name || activePeer?.full_name || "Собеседник",
    };
    replyBar.classList.remove("d-none");
    replyBarLabel.textContent = replyTarget.is_mine ? "Ответ себе" : `Ответ ${replyTarget.sender_name}`;
    replyBarText.textContent = replyTarget.body || "Вложение";
    messageInput.focus();
  }

  function clearReplyTarget() {
    replyTarget = null;
    replyBar.classList.add("d-none");
    replyBarText.textContent = "";
  }

  function messagePreviewText(msg) {
    if (msg.body && msg.body.trim()) return msg.body.trim();
    if (msg.file?.name) return msg.file.name;
    if (msg.has_attachment) return "Вложение";
    return "Сообщение";
  }

  function clearPendingFiles() {
    pendingFiles.forEach((item) => {
      if (item.url) URL.revokeObjectURL(item.url);
    });
    pendingFiles = [];
    renderAttachPreview();
  }

  function renderAttachPreview() {
    attachPreview.innerHTML = "";
    if (!pendingFiles.length) {
      attachPreview.classList.add("d-none");
      return;
    }
    attachPreview.classList.remove("d-none");
    pendingFiles.forEach((item, index) => {
      const wrap = document.createElement("div");
      wrap.className = "tg-attach-preview__item";
      if (item.url) {
        const img = document.createElement("img");
        img.src = item.url;
        img.alt = item.file.name;
        wrap.appendChild(img);
      } else {
        const icon = document.createElement("div");
        icon.className = "tg-attach-preview__file";
        icon.innerHTML = '<i class="bi bi-file-earmark"></i>';
        wrap.appendChild(icon);
      }
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tg-attach-preview__remove";
      remove.title = "Убрать";
      remove.innerHTML = '<i class="bi bi-x"></i>';
      remove.addEventListener("click", () => {
        const removed = pendingFiles.splice(index, 1)[0];
        if (removed?.url) URL.revokeObjectURL(removed.url);
        renderAttachPreview();
      });
      wrap.appendChild(remove);
      attachPreview.appendChild(wrap);
    });
  }

  function queueFiles(fileList) {
    Array.from(fileList || []).forEach((file, index) => {
      let ready = file;
      if (file.type.startsWith("image/") && (!file.name || file.name === "image.png")) {
        const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
        ready = new File([file], `screenshot-${Date.now()}-${index}.${ext}`, {
          type: file.type,
          lastModified: file.lastModified || Date.now(),
        });
      }
      const isImage = ready.type.startsWith("image/");
      pendingFiles.push({
        file: ready,
        url: isImage ? URL.createObjectURL(ready) : null,
      });
    });
    renderAttachPreview();
  }

  function handlePaste(e) {
    if (!activeConversationId) return;
    const clipboard = e.clipboardData;
    if (!clipboard) return;

    const files = [];
    if (clipboard.files?.length) {
      Array.from(clipboard.files).forEach((f) => files.push(f));
    } else if (clipboard.items?.length) {
      Array.from(clipboard.items).forEach((item) => {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      });
    }

    if (!files.length) return;
    e.preventDefault();
    queueFiles(files);
    messageInput.focus();
  }

  function closeChat() {
    if (!activeConversationId && chatView.classList.contains("d-none")) return;
    saveDraft();
    app.classList.remove("chat-open");
    chatView.classList.add("d-none");
    emptyState.classList.remove("d-none");
    activeConversationId = null;
    activePeer = null;
    messagesContainer.innerHTML = "";
    clearComposerState();
    stopPolling();
    document.querySelectorAll(".tg-list-item.active").forEach((el) => {
      el.classList.remove("active");
    });
  }

  function handleEscape() {
    if (!imageLightbox.classList.contains("d-none")) {
      closeLightbox();
      return;
    }
    if (replyTarget) {
      clearReplyTarget();
      return;
    }
    if (pendingFiles.length) {
      clearPendingFiles();
      return;
    }
    if (activeConversationId) {
      closeChat();
    }
  }

  function notifyIncomingMessage(msg, conversationId) {
    if (!notify || !msg || msg.is_mine) return;
    const viewingThis =
      !document.hidden &&
      activeConversationId &&
      String(activeConversationId) === String(conversationId);
    notify.notifyNewMessage({
      title: activePeer?.full_name || "Новое сообщение",
      body: messagePreviewText(msg),
      url: "/messenger/",
      messageId: msg.id,
      conversationId,
      skipSound: viewingThis,
      skipBrowser: viewingThis,
    });
  }

  function openLightbox(url, alt = "") {
    lightboxImage.src = url;
    lightboxImage.alt = alt;
    imageLightbox.classList.remove("d-none");
  }

  function closeLightbox() {
    imageLightbox.classList.add("d-none");
    lightboxImage.src = "";
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
    const statusHint = conv.peer.is_online ? "в сети" : formatPresence(conv.peer);
    body.innerHTML = `
      <div class="tg-list-item__top">
        <span class="tg-list-item__name">${escapeHtml(conv.peer.full_name)}</span>
        <span class="tg-list-item__time">${formatTime(conv.last_message_at)}</span>
      </div>
      <div class="tg-list-item__top">
        <span class="tg-list-item__preview ${conv.peer.is_online ? "is-online" : ""}">${escapeHtml(
          conv.last_message_preview || statusHint
        )}</span>
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
    const meta = [user.position, user.department].filter(Boolean).join(" · ") || user.email;
    body.innerHTML = `
      <div class="tg-list-item__name">${escapeHtml(user.full_name)}</div>
      <div class="tg-list-item__preview ${user.is_online ? "is-online" : ""}">${escapeHtml(
        formatPresence(user)
      )} · ${escapeHtml(meta)}${
        user.is_blocked ? ' <span class="text-danger">(заблокирован)</span>' : ""
      }${!user.is_active ? ' <span class="text-muted">(неактивен)</span>' : ""}</div>
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
      conversationList.innerHTML =
        '<div class="tg-list-empty">Нет диалогов. Начните переписку во вкладке «Контакты».</div>';
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
    if (activeConversationId && activeConversationId !== conversationId) {
      saveDraft();
    }

    activeConversationId = conversationId;
    activePeer = peer;
    lastMessageId = null;

    emptyState.classList.add("d-none");
    chatView.classList.remove("d-none");
    app.classList.add("chat-open");

    chatPeerName.textContent = peer.full_name;
    updatePeerStatus(peer);

    document.querySelectorAll(".tg-list-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.conversationId === conversationId);
    });

    messagesContainer.innerHTML = "";
    clearPendingFiles();
    restoreDraft(conversationId);

    await loadMessages(true);
    startPolling();
  }

  function renderMessage(msg) {
    const wrap = document.createElement("div");
    wrap.className = `tg-msg ${msg.is_mine ? "tg-msg--out" : "tg-msg--in"}`;
    wrap.dataset.messageId = msg.id;

    const actions = document.createElement("div");
    actions.className = "tg-msg__actions";
    const replyBtn = document.createElement("button");
    replyBtn.type = "button";
    replyBtn.className = "tg-msg__reply-btn";
    replyBtn.title = "Ответить";
    replyBtn.innerHTML = '<i class="bi bi-reply"></i>';
    replyBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setReplyTarget({
        id: msg.id,
        body: messagePreviewText(msg),
        is_mine: msg.is_mine,
        sender_name: msg.is_mine ? currentUserName : activePeer?.full_name,
      });
    });
    actions.appendChild(replyBtn);
    wrap.appendChild(actions);

    const bubble = document.createElement("div");
    bubble.className = "tg-bubble";

    if (msg.reply_to) {
      const replyBlock = document.createElement("div");
      replyBlock.className = "tg-bubble__reply";
      const author = msg.reply_to.is_mine
        ? currentUserName
        : msg.reply_to.sender_name || activePeer?.full_name || "Собеседник";
      replyBlock.innerHTML = `
        <div>
          <div class="tg-bubble__reply-author">${escapeHtml(author)}</div>
          <div class="tg-bubble__reply-text">${escapeHtml(msg.reply_to.body || "Вложение")}</div>
        </div>
      `;
      replyBlock.addEventListener("click", () => {
        const target = messagesContainer.querySelector(
          `.tg-msg[data-message-id="${msg.reply_to.id}"]`
        );
        if (!target) return;
        target.classList.add("tg-msg--highlight");
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => target.classList.remove("tg-msg--highlight"), 1200);
      });
      bubble.appendChild(replyBlock);
    }

    if (msg.has_attachment && msg.file) {
      if (msg.file.is_image) {
        const img = document.createElement("img");
        img.className = "tg-image-preview";
        img.src = msg.file.url;
        img.alt = msg.file.name || "Фото";
        img.loading = "lazy";
        img.addEventListener("click", () => openLightbox(msg.file.url, msg.file.name || "Фото"));
        bubble.appendChild(img);
      } else {
        const link = document.createElement("a");
        link.className = "tg-file-link";
        link.href = `${msg.file.url}?download=1`;
        link.target = "_blank";
        link.innerHTML = `<i class="bi bi-paperclip"></i> ${escapeHtml(msg.file.name)}`;
        bubble.appendChild(link);
      }
      if (msg.body) {
        const text = document.createElement("div");
        text.className = "mt-2";
        text.textContent = msg.body;
        bubble.appendChild(text);
      }
    } else {
      const text = document.createElement("div");
      text.textContent = msg.body || "";
      bubble.appendChild(text);
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
    const conversationId = activeConversationId;
    const res = await api(`/messenger/api/conversations/${conversationId}/messages`);
    if (!res.ok) return;
    const data = await res.json();
    if (conversationId !== activeConversationId) return;

    if (data.conversation?.peer) {
      activePeer = data.conversation.peer;
      updatePeerStatus(activePeer);
    }

    const stickToBottom = scrollBottom || isNearBottom(messagesContainer);
    const existingIds = new Set(
      [...messagesContainer.querySelectorAll(".tg-msg")].map((el) => el.dataset.messageId)
    );
    const isInitial = existingIds.size === 0;
    let appended = 0;

    data.messages.forEach((msg) => {
      if (!existingIds.has(msg.id)) {
        messagesContainer.appendChild(renderMessage(msg));
        lastMessageId = msg.id;
        appended += 1;
        if (!isInitial) {
          notifyIncomingMessage(msg, conversationId);
        }
      } else {
        const el = messagesContainer.querySelector(`.tg-msg[data-message-id="${msg.id}"]`);
        if (el && msg.is_mine) {
          const readEl = el.querySelector(".tg-bubble__read");
          if (readEl) readEl.textContent = msg.is_read ? "✓✓" : "✓";
        }
      }
    });

    if (scrollBottom || isInitial || (appended && stickToBottom)) {
      scrollMessagesToBottom();
    }

    await loadConversations();
    updateGlobalUnread();
  }

  async function sendMessage() {
    const body = messageInput.value.trim();
    const hasFiles = pendingFiles.length > 0;
    if ((!body && !hasFiles) || !activeConversationId) return;

    sendBtn.disabled = true;
    const conversationId = activeConversationId;
    const replyId = replyTarget?.id || null;

    try {
      if (hasFiles) {
        const files = pendingFiles.slice();
        clearPendingFiles();
        let replyUsed = false;
        for (const item of files) {
          await sendFile(item.file, replyUsed ? null : replyId);
          replyUsed = true;
        }
        if (body) {
          await postTextMessage(body, replyUsed ? null : replyId);
        }
      } else {
        await postTextMessage(body, replyId);
      }

      if (conversationId === activeConversationId) {
        messageInput.value = "";
        messageInput.style.height = "auto";
        clearReplyTarget();
        drafts.delete(conversationId);
        scrollMessagesToBottom();
      }
    } finally {
      sendBtn.disabled = false;
    }
  }

  async function postTextMessage(body, replyId) {
    const payload = { body };
    if (replyId) payload.reply_to_id = replyId;
    const res = await api(`/messenger/api/conversations/${activeConversationId}/messages`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!messagesContainer.querySelector(`.tg-msg[data-message-id="${data.message.id}"]`)) {
      messagesContainer.appendChild(renderMessage(data.message));
    }
    lastMessageId = data.message.id;
    await loadConversations();
  }

  async function sendFile(file, replyId = null) {
    if (!file || !activeConversationId) return;
    const form = new FormData();
    form.append("file", file);
    if (replyId) form.append("reply_to_id", replyId);
    const res = await api(`/messenger/api/conversations/${activeConversationId}/attachments`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!messagesContainer.querySelector(`.tg-msg[data-message-id="${data.message.id}"]`)) {
      messagesContainer.appendChild(renderMessage(data.message));
    }
    lastMessageId = data.message.id;
    await loadConversations();
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
        <div class="tg-search-result__text">${escapeHtml(
          item.message.body || item.message.file?.name || ""
        )}</div>
      `;
      row.addEventListener("click", () => openConversation(item.conversation_id, item.peer));
      searchResults.appendChild(row);
    });
  }

  async function heartbeat() {
    await api("/messenger/api/heartbeat", { method: "POST" });
  }

  async function updateGlobalUnread(count, preview = null) {
    let total = count;
    let previewData = preview;
    if (total === undefined) {
      const headers = {};
      if (unreadEtag) headers["If-None-Match"] = unreadEtag;
      const res = await api("/messenger/api/unread-count", { headers });
      if (res.status === 304) return;
      if (res.ok) {
        unreadEtag = res.headers.get("ETag") || unreadEtag;
        const data = await res.json();
        total = data.total;
        previewData = data.preview || null;
      }
    }
    if (typeof total === "number") {
      if (
        knownUnreadTotal !== null &&
        total > knownUnreadTotal &&
        notify
      ) {
        notify.onUnreadIncrease(total, previewData, {
          activeConversationId,
        });
      }
      knownUnreadTotal = total;
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
      loadMessages(false);
    };
    pollTimer = setInterval(tick, pollIntervalMs);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  function startUnreadPolling() {
    clearInterval(unreadPollTimer);
    const tick = () => {
      if (document.hidden) return;
      updateGlobalUnread();
    };
    unreadPollTimer = setInterval(tick, unreadIntervalMs);
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
  messageInput.addEventListener("paste", handlePaste);
  app.addEventListener("paste", (e) => {
    if (e.target === messageInput) return;
    handlePaste(e);
  });
  messageInput.addEventListener("input", () => {
    messageInput.style.height = "auto";
    messageInput.style.height = `${Math.min(messageInput.scrollHeight, 120)}px`;
    if (activeConversationId) {
      drafts.set(activeConversationId, {
        text: messageInput.value,
        reply: replyTarget,
      });
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files?.length) {
      queueFiles(fileInput.files);
      fileInput.value = "";
    }
  });

  // Drag & drop файлов в окно чата
  ["dragenter", "dragover"].forEach((evtName) => {
    chatView.addEventListener(evtName, (e) => {
      if (!activeConversationId) return;
      e.preventDefault();
      e.stopPropagation();
    });
  });
  chatView.addEventListener("drop", (e) => {
    if (!activeConversationId) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer?.files?.length) {
      queueFiles(e.dataTransfer.files);
    }
  });

  replyBarClose?.addEventListener("click", clearReplyTarget);
  lightboxClose?.addEventListener("click", closeLightbox);
  imageLightbox?.addEventListener("click", (e) => {
    if (e.target === imageLightbox) closeLightbox();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      handleEscape();
    }
  });

  chatBackBtn?.addEventListener("click", closeChat);

  document.addEventListener(
    "click",
    () => notify?.requestPermission(),
    { once: true }
  );

  heartbeat();
  heartbeatTimer = setInterval(heartbeat, 30000);
  loadConversations();
  loadUsers();
  updateGlobalUnread();
  startUnreadPolling();

  window.addEventListener("beforeunload", () => {
    clearInterval(pollTimer);
    clearInterval(heartbeatTimer);
    clearInterval(unreadPollTimer);
  });
})();
