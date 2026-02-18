(function () {
  "use strict";

  const chatWindow = document.getElementById("chatWindow");
  const welcome = document.getElementById("welcome");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("messageInput");
  const sendBtn = document.getElementById("sendBtn");

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function appendMessage(role, content) {
    if (welcome) welcome.style.display = "none";
    const msg = document.createElement("div");
    msg.className = "msg " + role;
    msg.setAttribute("data-role", role);
    const label = role === "user" ? "You" : "Agent";
    msg.innerHTML =
      '<span class="role-label">' +
      escapeHtml(label) +
      "</span>" +
      escapeHtml(content).replace(/\n/g, "<br>");
    chatWindow.appendChild(msg);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function setLoading(loading) {
    sendBtn.disabled = loading;
    input.disabled = loading;
    sendBtn.classList.toggle("loading", loading);
  }

  function showError(message) {
    const err = document.createElement("div");
    err.className = "msg agent error-msg";
    err.setAttribute("data-role", "agent");
    err.textContent = message;
    chatWindow.appendChild(err);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  async function loadHistory() {
    try {
      const res = await fetch("/api/history");
      if (!res.ok) return;
      const data = await res.json();
      const history = data.history || [];
      if (history.length === 0) return;
      if (welcome) welcome.style.display = "none";
      history.forEach(function (entry) {
        appendMessage(entry.role, entry.content);
      });
      chatWindow.scrollTop = chatWindow.scrollHeight;
    } catch (_) {}
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    const text = (input.value || "").trim();
    if (!text) return;

    appendMessage("user", text);
    input.value = "";
    input.style.height = "auto";
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();

      if (!res.ok) {
        showError(data.error || "Something went wrong.");
        return;
      }
      appendMessage("assistant", data.response || "");
    } catch (err) {
      showError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  });

  // Auto-resize textarea
  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  loadHistory();
})();
