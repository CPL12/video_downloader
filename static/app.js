const urlInput = document.getElementById("urlInput");
const fetchBtn = document.getElementById("fetchBtn");
const clearBtn = document.getElementById("clearBtn");
const statusEl = document.getElementById("status");
const formatsPanel = document.getElementById("formatsPanel");
const mp4Options = document.getElementById("mp4Options");
const mp3Options = document.getElementById("mp3Options");
const mp3Quality = document.getElementById("mp3Quality");
const downloadBtn = document.getElementById("downloadBtn");
const titleHeading = document.getElementById("titleHeading");
const downloadForm = document.getElementById("downloadForm");
const typeToggle = document.getElementById("typeToggle");
const progressContainer = document.getElementById("progressContainer");
const progressFill = document.getElementById("progressFill");
const progressText = document.getElementById("progressText");
const clearTempBtn = document.getElementById("clearTempBtn");

let currentData = null;
// State machine for high-res downloads: "idle" | "preparing" | "ready"
let downloadState = "idle";
let prepareAbort = null; // AbortController instance

function setStatus(message, kind = "info") {
  if (!message) {
    statusEl.className = "";
    statusEl.textContent = "";
    return;
  }
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

function formatBytes(bytes) {
  if (!bytes || Number.isNaN(bytes)) return "Size unknown";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[index]}`;
}

function showProgress(pct, speed, eta) {
  progressContainer.classList.remove("hidden");
  progressFill.style.width = `${Math.min(pct, 100)}%`;

  let text = `${pct.toFixed(1)}%`;
  if (speed && speed !== "0 KiB/s" && speed !== "cached") {
    text += `  ?  ${speed}`;
  }
  if (eta && eta !== "unknown" && eta !== "00:00") {
    text += `  ?  ETA: ${eta}`;
  }
  progressText.textContent = text;
}

function hideProgress() {
  progressContainer.classList.add("hidden");
  progressFill.style.width = "0%";
  progressText.textContent = "";
}

function resetDownloadButton() {
  downloadBtn.textContent = "Download";
  downloadBtn.classList.remove("ready", "stop");
  downloadBtn.disabled = false;
  downloadState = "idle";
}

function renderMp4Options(formats) {
  mp4Options.innerHTML = "";

  if (!formats || formats.length === 0) {
    const note = document.createElement("div");
    note.className = "status error";
    note.textContent = "No MP4 video formats were found for this URL. Try MP3 or another source.";
    mp4Options.appendChild(note);
    return;
  }

  formats.forEach((fmt, index) => {
    const option = document.createElement("label");
    option.className = "option";

    const input = document.createElement("input");
    input.type = "radio";
    input.name = "mp4Format";
    input.value = fmt.format_id;
    input.dataset.height = fmt.height || "";
    if (index === 0) input.checked = true;

    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "option-title";
    const fps = fmt.fps ? `${fmt.fps}fps` : "";
    title.textContent = `${fmt.height}p ${fps}`.trim();

    const meta = document.createElement("div");
    meta.className = "option-meta";
    const size = formatBytes(fmt.filesize);
    const bitrate = fmt.tbr ? `${Math.round(fmt.tbr)} kbps` : "";

    let metaText = [size, bitrate].filter(Boolean).join(" ? ");
    if (fmt.need_merge) {
      metaText += " (High Quality)";
    }
    meta.textContent = metaText;

    body.appendChild(title);
    body.appendChild(meta);

    option.appendChild(input);
    option.appendChild(body);
    mp4Options.appendChild(option);
  });
}

function renderMp3Options(qualities) {
  mp3Quality.innerHTML = "";
  qualities.forEach((quality) => {
    const option = document.createElement("option");
    option.value = quality;
    option.textContent = `${quality} kbps`;
    if (quality === 192) option.selected = true;
    mp3Quality.appendChild(option);
  });
}

function updateTypeView() {
  const selected = document.querySelector("input[name='downloadType']:checked");
  const type = selected ? selected.value : "mp4";
  if (type === "mp3") {
    mp3Options.classList.remove("hidden");
    mp4Options.classList.add("hidden");
  } else {
    mp4Options.classList.remove("hidden");
    mp3Options.classList.add("hidden");
  }
}


async function fetchFormats() {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("Please paste a URL first.", "error");
    return;
  }

  setStatus("Fetching available formats...", "info");
  formatsPanel.classList.add("hidden");
  // Reset download state and UI
  stopPreparation();
  resetDownloadButton();
  hideProgress();

  try {
    const params = new URLSearchParams({ url });
    const response = await fetch(`/api/formats?${params.toString()}`);
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Failed to load formats.");
    }
    const data = await response.json();
    currentData = data;

    titleHeading.textContent = `Available formats for: ${data.title}`;
    renderMp4Options(data.mp4);
    renderMp3Options(data.mp3_qualities || []);
    formatsPanel.classList.remove("hidden");
    updateTypeView();
    setStatus("Formats loaded. Pick your quality and download.", "info");
  } catch (error) {
    setStatus(error.message || "Failed to load formats.", "error");
  }
}

function fillFormFields(formData) {
  for (const field of downloadForm.elements) {
    if (field.name && formData.has(field.name)) {
      field.value = formData.get(field.name);
    }
  }
}

function buildFormData() {
  const type = document.querySelector("input[name='downloadType']:checked").value;
  const url = urlInput.value.trim();
  const formData = new FormData();
  formData.set("url", url);
  formData.set("type", type);
  formData.set("title", currentData.title || "download");

  if (type === "mp4") {
    const selectedInput = document.querySelector("input[name='mp4Format']:checked");
    if (!selectedInput) return null;
    formData.set("format_id", selectedInput.value);
    formData.set("audio_quality", "");
  } else {
    formData.set("format_id", "");
    formData.set("audio_quality", mp3Quality.value);
  }
  return formData;
}

async function startPreparation(url, formatId, title) {
  const params = new URLSearchParams({
    url,
    format_id: formatId,
    title
  });

  downloadState = "preparing";
  prepareAbort = new AbortController();

  // Update button to "Stop"
  downloadBtn.textContent = "Stop Preparation";
  downloadBtn.classList.add("stop");
  downloadBtn.disabled = false;

  // Show base progress
  showProgress(0, "", "");

  try {
    while (true) {
      const response = await fetch(`/api/prepare?${params.toString()}`, {
        signal: prepareAbort.signal
      });
      if (!response.ok) throw new Error("Preparation request failed");
      const status = await response.json();

      if (status.status === "finished") {
        // Preparation done! Switch to "ready" state
        downloadState = "ready";
        downloadBtn.disabled = false;
        downloadBtn.textContent = "⬇ Download Ready — Click to Save";
        downloadBtn.classList.remove("stop");
        downloadBtn.classList.add("ready");

        showProgress(100, status.speed || "", "");
        setStatus("File is ready! Click the button to start downloading.", "info");
        return;
      }

      if (status.status === "merging") {
        downloadBtn.textContent = "Merging Video & Audio...";
        downloadBtn.disabled = true;
        downloadBtn.classList.remove("stop");
        showProgress(100, "merging", "");
        setStatus("Almost done! Merging video and audio streams...", "info");
      } else if (status.status === "error") {
        throw new Error(status.error || "Preparation failed");
      } else {
        // Update independent progress bar
        const pct = status.progress || 0;
        showProgress(pct, status.speed || "", status.eta || "");
        setStatus("Preparing your high-resolution download...", "info");
      }

      await new Promise(r => setTimeout(r, 1000));
    }
  } catch (err) {
    if (err.name === "AbortError") {
      setStatus("Preparation stopped by user.", "info");
    } else {
      setStatus(err.message || "Preparation failed.", "error");
    }
    resetDownloadButton();
    hideProgress();
  }
}

function stopPreparation() {
  if (prepareAbort) {
    prepareAbort.abort();
    prepareAbort = null;
  }
}

function triggerDownload() {
  if (!currentData) {
    setStatus("Fetch formats before downloading.", "error");
    return;
  }

  // STATE: "preparing" — user clicked "Stop"
  if (downloadState === "preparing") {
    stopPreparation();
    return;
  }

  // STATE: "ready" — user clicked after preparation finished.
  if (downloadState === "ready") {
    const formData = buildFormData();
    if (!formData) {
      setStatus("Select an MP4 resolution.", "error");
      return;
    }
    fillFormFields(formData);

    // Reset for next time
    resetDownloadButton();
    hideProgress();

    setStatus("Download starting — your browser or download manager will handle it.", "info");
    downloadForm.submit();
    return;
  }

  // STATE: "idle" — start a new download
  const type = document.querySelector("input[name='downloadType']:checked").value;
  if (type === "mp4") {
    const selectedInput = document.querySelector("input[name='mp4Format']:checked");
    if (!selectedInput) {
      setStatus("Select an MP4 resolution.", "error");
      return;
    }
    const formatId = selectedInput.value;
    const fmt = currentData.mp4.find(f => f.format_id === formatId);

    if (fmt && fmt.need_merge) {
      // High quality: start preparation
      startPreparation(urlInput.value.trim(), formatId, currentData.title);
      return;
    }
  }

  // Standard quality: direct form submit
  const formData = buildFormData();
  if (!formData) {
    setStatus("Select a format.", "error");
    return;
  }
  fillFormFields(formData);
  setStatus("Download starting — your browser or download manager will handle it.", "info");
  downloadForm.submit();
}

fetchBtn.addEventListener("click", fetchFormats);
clearBtn.addEventListener("click", () => {
  urlInput.value = "";
  formatsPanel.classList.add("hidden");
  currentData = null;
  stopPreparation();
  resetDownloadButton();
  hideProgress();
  setStatus("", "info");
});

downloadBtn.addEventListener("click", triggerDownload);

clearTempBtn.addEventListener("click", async () => {
  if (!confirm("Are you sure you want to clear ALL temporary files and active tasks from the server?")) {
    return;
  }

  setStatus("Cleaning up server files...", "info");
  try {
    const response = await fetch("/api/clear_temp", { method: "DELETE" });
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Failed to clear temporary files.");
    }
    const result = await response.json();

    // Clear local UI state as well
    stopPreparation();
    resetDownloadButton();
    hideProgress();

    setStatus(result.message, "info");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

Array.from(typeToggle.querySelectorAll("input")).forEach((input) => {
  input.addEventListener("change", updateTypeView);
});

updateTypeView();
