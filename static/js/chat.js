/** DRUVO Chat — floating customer assistant widget. */

const STORAGE_KEY = "druvo_chat_history_v1";

const root = document.getElementById("druvo-chat-root");
if (!root) {
  // Widget not on page
} else {
  const launcher = document.getElementById("druvo-chat-launcher");
  const panel = document.getElementById("druvo-chat-panel");
  const closeBtn = document.getElementById("druvo-chat-close");
  const messagesEl = document.getElementById("druvo-chat-messages");
  const form = document.getElementById("druvo-chat-form");
  const input = document.getElementById("druvo-chat-input");
  const sendBtn = document.getElementById("druvo-chat-send");

  let history = loadHistory();
  let welcomeShown = false;
  let sending = false;

  function loadHistory() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-16)));
    } catch {
      /* ignore quota errors */
    }
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatReply(text) {
    const safe = escapeHtml(text);
    return safe
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function appendMessage(role, content) {
    const bubble = document.createElement("div");
    bubble.className = `druvo-chat-bubble druvo-chat-bubble--${role}`;
    bubble.innerHTML = formatReply(content);
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function renderHistory() {
    messagesEl.innerHTML = "";
    for (const item of history) {
      appendMessage(item.role === "user" ? "user" : "assistant", item.content);
    }
  }

  function setOpen(open) {
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      if (!welcomeShown && history.length === 0) {
        showWelcome();
      } else {
        renderHistory();
      }
      input.focus();
    }
  }

  async function showWelcome() {
    welcomeShown = true;
    try {
      const res = await fetch("/api/chat/status");
      if (res.ok) {
        const data = await res.json();
        appendMessage("assistant", data.welcome || "Hello! How can I help you today?");
        return;
      }
    } catch {
      /* fall through */
    }
    appendMessage(
      "assistant",
      "Hello! I'm DRUVO Chat. Ask me about products, delivery, returns, or your orders."
    );
  }

  async function sendMessage(text) {
    if (sending) return;
    const trimmed = text.trim();
    if (!trimmed) return;

    sending = true;
    sendBtn.disabled = true;
    input.disabled = true;

    appendMessage("user", trimmed);
    history.push({ role: "user", content: trimmed });
    saveHistory();

    const typing = document.createElement("div");
    typing.className = "druvo-chat-bubble druvo-chat-bubble--assistant druvo-chat-typing";
    typing.textContent = "DRUVO Chat is typing…";
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          history: history.slice(0, -1).slice(-8),
        }),
      });

      typing.remove();

      if (res.status === 429) {
        appendMessage(
          "assistant",
          "You're sending messages quite quickly. Please wait a moment and try again."
        );
        return;
      }

      if (!res.ok) {
        appendMessage(
          "assistant",
          "Sorry, I'm having trouble right now. Please email druvo.uk@gmail.com and we'll help you."
        );
        return;
      }

      const data = await res.json();
      const reply = data.reply || "I'm not sure about that. Please contact us at druvo.uk@gmail.com.";
      appendMessage("assistant", reply);
      history.push({ role: "assistant", content: reply });
      saveHistory();
    } catch {
      typing.remove();
      appendMessage(
        "assistant",
        "Connection issue — please try again or email druvo.uk@gmail.com."
      );
    } finally {
      sending = false;
      sendBtn.disabled = false;
      input.disabled = false;
      input.value = "";
      input.focus();
    }
  }

  launcher.addEventListener("click", () => setOpen(panel.hidden));
  closeBtn.addEventListener("click", () => setOpen(false));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      setOpen(false);
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input.value);
    }
  });
}
