document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("shorten-form");
  if (!form) return;

  const urlInput = document.getElementById("url");
  const aliasInput = document.getElementById("alias");
  const submitBtn = document.getElementById("submit-btn");
  const resultDiv = document.getElementById("result");
  const errorDiv = document.getElementById("error-msg");
  const shortUrlLink = document.getElementById("short-url");
  const copyBtn = document.getElementById("copy-btn");
  const statsLink = document.getElementById("stats-link");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    resultDiv.style.display = "none";
    errorDiv.style.display = "none";
    submitBtn.disabled = true;
    submitBtn.textContent = "Shortening...";

    const payload = { url: urlInput.value.trim() };
    const alias = aliasInput.value.trim();
    if (alias) payload.custom_alias = alias;

    try {
      const res = await fetch("/api/shorten", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Something went wrong");
      }

      shortUrlLink.href = data.short_url;
      shortUrlLink.textContent = data.short_url;
      statsLink.href = `/stats/${data.short_code}`;
      resultDiv.style.display = "block";
    } catch (err) {
      errorDiv.textContent = err.message;
      errorDiv.style.display = "block";
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Shorten URL";
    }
  });

  copyBtn.addEventListener("click", async () => {
    const url = shortUrlLink.textContent;
    try {
      await navigator.clipboard.writeText(url);
      copyBtn.textContent = "Copied!";
      setTimeout(() => {
        copyBtn.textContent = "Copy";
      }, 2000);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      copyBtn.textContent = "Copied!";
      setTimeout(() => {
        copyBtn.textContent = "Copy";
      }, 2000);
    }
  });
});
