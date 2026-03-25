const urlInput = document.getElementById("urlInput");
const fetchBtn = document.getElementById("fetchBtn");
const clearBtn = document.getElementById("clearBtn");
const statusEl = document.getElementById("status");
const formatsPanel = document.getElementById("formatsPanel");
const mp4Options = document.getElementById("mp4Options");
const mp3Options = document.getElementById("mp3Options");
const mp3Quality = document.getElementById("mp3Quality");
const mp3QualityLabel =
  document.getElementById("mp3QualityLabel") || document.querySelector("label[for='mp3Quality']");
const downloadBtn = document.getElementById("downloadBtn");
const titleHeading = document.getElementById("titleHeading");
const downloadForm = document.getElementById("downloadForm");
const typeToggle = document.getElementById("typeToggle");
const progressContainer = document.getElementById("progressContainer");
const progressFill = document.getElementById("progressFill");
const progressText = document.getElementById("progressText");
const clearTempBtn = document.getElementById("clearTempBtn");

let currentData = null;
let downloadState = "idle";
let prepareAbort = null;
let playlistTaskId = null;
let playlistTaskSignature = "";
const pageParams = new URLSearchParams(window.location.search);
const demoMode = pageParams.get("demo");

if (pageParams.get("theme") === "light") {
  document.documentElement.dataset.theme = "light";
}

function setStatus(message, kind = "info") {
  if (!message) {
    statusEl.className = "";
    statusEl.textContent = "";
    return;
  }
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

function setElementText(element, text) {
  if (element) {
    element.textContent = text;
  }
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

function showProgress(pct, speed, eta, phaseLabel = "", detail = "") {
  progressContainer.classList.remove("hidden");
  progressFill.style.width = `${Math.min(pct, 100)}%`;

  let text = `${pct.toFixed(1)}%`;
  if (phaseLabel) {
    text = `${phaseLabel} | ${text}`;
  }
  if (speed && speed !== "0 KiB/s" && speed !== "cached") {
    text += ` | ${speed}`;
  }
  if (eta && eta !== "unknown" && eta !== "00:00") {
    text += ` | ETA: ${eta}`;
  }
  if (detail) {
    text += ` | ${detail}`;
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

function triggerPreparedDownload(taskId, filename = "") {
  const link = document.createElement("a");
  link.href = `/api/download_prepared?task_id=${encodeURIComponent(taskId)}`;
  if (filename) {
    link.download = filename;
  }
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function buildFormSignature(formData) {
  const params = new URLSearchParams();
  for (const [name, value] of formData.entries()) {
    params.set(name, value);
  }
  return params.toString();
}

function renderMp4Options(formats, isPlaylist = false) {
  mp4Options.innerHTML = "";

  if (!formats || formats.length === 0) {
    const note = document.createElement("div");
    note.className = "status error";
    note.textContent = "No MP4 video formats were found for this URL. Try MP3 or another source.";
    mp4Options.appendChild(note);
    return;
  }

  const defaultHeight = isPlaylist && formats.some((fmt) => Number(fmt.height) === 720)
    ? 720
    : Number(formats[0].height || 0);

  formats.forEach((fmt, index) => {
    const option = document.createElement("label");
    option.className = "option";

    const input = document.createElement("input");
    input.type = "radio";
    input.name = "mp4Format";
    input.value = fmt.format_id;
    input.dataset.height = fmt.height || "";
    if ((isPlaylist && Number(fmt.height) === defaultHeight) || (!isPlaylist && index === 0)) {
      input.checked = true;
    }

    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "option-title";
    const fps = fmt.fps ? `${fmt.fps}fps` : "";
    title.textContent = `${fmt.height}p ${fps}`.trim();

    const meta = document.createElement("div");
    meta.className = "option-meta";
    let metaText = "";
    if (isPlaylist) {
      metaText = `Best available up to ${fmt.height}p for each playlist item`;
    } else {
      const size = formatBytes(fmt.filesize);
      const bitrate = fmt.tbr ? `${Math.round(fmt.tbr)} kbps` : "";
      metaText = [size, bitrate].filter(Boolean).join(" | ");
      if (fmt.need_merge) {
        metaText += " (High Quality)";
      }
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

  playlistTaskId = null;
  playlistTaskSignature = "";
  setStatus("Fetching available formats...", "info");
  formatsPanel.classList.add("hidden");
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

    if (data.is_playlist) {
      const countLabel = data.entry_count === 1 ? "1 item" : `${data.entry_count} items`;
      setElementText(titleHeading, `Playlist: ${data.title} (${countLabel})`);
      setElementText(mp3QualityLabel, "MP3 quality for ZIP archive");
      renderMp4Options(data.mp4, true);
      setStatus("Playlist loaded. The download will be packaged as a ZIP archive.", "info");
    } else {
      setElementText(titleHeading, `Available formats for: ${data.title}`);
      setElementText(mp3QualityLabel, "MP3 quality");
      renderMp4Options(data.mp4, false);
      setStatus("Formats loaded. Pick your quality and download.", "info");
    }
    renderMp3Options(data.mp3_qualities || []);
    formatsPanel.classList.remove("hidden");
    updateTypeView();
  } catch (error) {
    setStatus(error.message || "Failed to load formats.", "error");
  }
}

function fillFormFields(formData) {
  for (const [name, value] of formData.entries()) {
    let field = downloadForm.querySelector(`[name="${name}"]`);
    if (!field) {
      field = document.createElement("input");
      field.type = "hidden";
      field.name = name;
      downloadForm.appendChild(field);
    }
    field.value = value;
  }
}

function buildFormData() {
  const type = document.querySelector("input[name='downloadType']:checked").value;
  const url = urlInput.value.trim();
  const formData = new FormData();
  formData.set("url", url);
  formData.set("type", type);
  formData.set("title", currentData.title || "download");
  formData.set("is_playlist", currentData.is_playlist ? "true" : "");

  if (type === "mp4") {
    const selectedInput = document.querySelector("input[name='mp4Format']:checked");
    if (!selectedInput) return null;
    formData.set("format_id", selectedInput.value);
    formData.set("height", selectedInput.dataset.height || "");
    formData.set("audio_quality", "");
  } else {
    formData.set("format_id", "");
    formData.set("height", "");
    formData.set("audio_quality", mp3Quality.value);
  }
  return formData;
}

async function startPlaylistPreparation(formData) {
  const signature = buildFormSignature(formData);
  const params = new URLSearchParams(signature);
  playlistTaskId = null;
  playlistTaskSignature = signature;
  downloadState = "preparing";
  prepareAbort = new AbortController();

  downloadBtn.textContent = "Stop Preparation";
  downloadBtn.classList.add("stop");
  downloadBtn.classList.remove("ready");
  downloadBtn.disabled = false;

  showProgress(0, "", "", "Preparing Playlist", "Waiting to start playlist download...");

  try {
    while (true) {
      const response = await fetch(`/api/prepare_playlist?${params.toString()}`, {
        signal: prepareAbort.signal,
      });
      if (!response.ok) {
        let message = "Playlist preparation request failed";
        try {
          const err = await response.json();
          message = err.detail || message;
        } catch {
          // Ignore JSON parse errors for non-JSON responses.
        }
        throw new Error(message);
      }

      const status = await response.json();
      if (status.task_id) {
        playlistTaskId = status.task_id;
      }

      if (status.status === "finished") {
        downloadState = "ready";
        downloadBtn.disabled = false;
        downloadBtn.textContent = "Download Ready - Click to Save";
        downloadBtn.classList.remove("stop");
        downloadBtn.classList.add("ready");

        showProgress(100, "", "", status.phase_label || "Ready", status.message || "");
        setStatus(status.message || "Playlist archive is ready. Click the button to save it.", "info");
        return;
      }

      if (status.status === "error") {
        throw new Error(status.error || status.message || "Playlist preparation failed");
      }

      const isArchiving = status.phase === "archive";
      downloadBtn.textContent = isArchiving ? "Packaging Playlist ZIP..." : "Stop Preparation";
      downloadBtn.disabled = isArchiving;
      downloadBtn.classList.toggle("stop", !isArchiving);

      showProgress(
        status.progress || 0,
        status.progress >= 100 ? "" : status.speed || "",
        status.eta || "",
        status.phase_label || "Preparing Playlist",
        status.message || ""
      );
      setStatus(status.message || "Preparing playlist archive...", "info");

      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (err) {
    if (err.name === "AbortError") {
      setStatus("Preparation stopped by user.", "info");
    } else {
      setStatus(err.message || "Playlist preparation failed.", "error");
    }
    resetDownloadButton();
    hideProgress();
  }
}

async function startPreparation(url, formatId, title, height) {
  const params = new URLSearchParams({
    url,
    format_id: formatId,
    title,
    height: height || "",
  });

  downloadState = "preparing";
  prepareAbort = new AbortController();

  downloadBtn.textContent = "Stop Preparation";
  downloadBtn.classList.add("stop");
  downloadBtn.disabled = false;

  showProgress(0, "", "");

  try {
    while (true) {
      const response = await fetch(`/api/prepare?${params.toString()}`, {
        signal: prepareAbort.signal,
      });
      if (!response.ok) throw new Error("Preparation request failed");
      const status = await response.json();

      if (status.status === "finished") {
        downloadState = "ready";
        downloadBtn.disabled = false;
        downloadBtn.textContent = "Download Ready - Click to Save";
        downloadBtn.classList.remove("stop");
        downloadBtn.classList.add("ready");

        showProgress(100, "", "", status.phase_label || "Ready", status.message || "");
        setStatus(status.message || "File is ready. Click the button to start downloading.", "info");
        return;
      }

      if (status.status === "merging") {
        downloadBtn.textContent = "Merging Video and Audio...";
        downloadBtn.disabled = true;
        downloadBtn.classList.remove("stop");
        showProgress(
          status.progress || 0,
          "",
          "",
          status.phase_label || "Merging Video and Audio",
          status.message || ""
        );
        setStatus(status.message || "Merging video and audio streams...", "info");
      } else if (status.status === "error") {
        throw new Error(status.error || "Preparation failed");
      } else {
        showProgress(
          status.progress || 0,
          status.progress >= 100 ? "" : status.speed || "",
          status.eta || "",
          status.phase_label || "Preparing Download",
          status.message || ""
        );
        setStatus(status.message || "Preparing your high-resolution download...", "info");
      }

      await new Promise((resolve) => setTimeout(resolve, 1000));
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

  if (downloadState === "preparing") {
    stopPreparation();
    return;
  }

  if (downloadState === "ready") {
    if (currentData.is_playlist) {
      const formData = buildFormData();
      if (!formData) {
        setStatus("Select a format.", "error");
        return;
      }
      const currentSignature = buildFormSignature(formData);
      if (currentSignature !== playlistTaskSignature) {
        startPlaylistPreparation(formData);
        return;
      }
      if (!playlistTaskId) {
        setStatus("Playlist archive is not ready yet.", "error");
        return;
      }
      const finishedTaskId = playlistTaskId;
      playlistTaskId = null;
      playlistTaskSignature = "";
      resetDownloadButton();
      hideProgress();
      setStatus("Download starting - your browser will save the playlist ZIP.", "info");
      triggerPreparedDownload(finishedTaskId, currentData.title || "playlist");
      return;
    }

    const formData = buildFormData();
    if (!formData) {
      setStatus("Select an MP4 resolution.", "error");
      return;
    }
    fillFormFields(formData);
    resetDownloadButton();
    hideProgress();
    setStatus("Download starting - your browser or download manager will handle it.", "info");
    downloadForm.submit();
    return;
  }

  if (currentData.is_playlist) {
    const formData = buildFormData();
    if (!formData) {
      setStatus("Select a format.", "error");
      return;
    }
    startPlaylistPreparation(formData);
    return;
  }

  const type = document.querySelector("input[name='downloadType']:checked").value;
  if (!currentData.is_playlist && type === "mp4") {
    const selectedInput = document.querySelector("input[name='mp4Format']:checked");
    if (!selectedInput) {
      setStatus("Select an MP4 resolution.", "error");
      return;
    }
    const formatId = selectedInput.value;
    const fmt = currentData.mp4.find((item) => item.format_id === formatId);

    if (fmt && fmt.need_merge) {
      startPreparation(urlInput.value.trim(), formatId, currentData.title, fmt.height);
      return;
    }
  }

  const formData = buildFormData();
  if (!formData) {
    setStatus("Select a format.", "error");
    return;
  }
  fillFormFields(formData);
  if (currentData.is_playlist) {
    setStatus("Playlist download is being built as a ZIP archive. Your browser will save it when it is ready.", "info");
  } else {
    setStatus("Download starting - your browser or download manager will handle it.", "info");
  }
  downloadForm.submit();
}

function applyDemoState() {
  if (!demoMode) {
    return;
  }

  if (demoMode === "overview") {
    urlInput.value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
    setStatus("Paste a link and fetch formats to download MP4 or MP3 directly from your browser.", "info");
    return;
  }

  if (demoMode === "workflow") {
    urlInput.value = "https://www.bilibili.com/video/BV1xx411c7mD";
    currentData = {
      title: "Sunset City Session",
      is_playlist: false,
      entry_count: 1,
      mp4: [
        { format_id: "137", height: 1080, fps: 60, tbr: 5820, filesize: 148897792, need_merge: true },
        { format_id: "22", height: 720, fps: 30, tbr: 2100, filesize: 50331648, need_merge: false },
        { format_id: "18", height: 360, fps: 30, tbr: 780, filesize: 19922944, need_merge: false },
      ],
      mp3_qualities: [128, 192, 256, 320],
    };

    setElementText(titleHeading, `Available formats for: ${currentData.title}`);
    renderMp4Options(currentData.mp4);
    renderMp3Options(currentData.mp3_qualities);
    formatsPanel.classList.remove("hidden");
    updateTypeView();

    downloadState = "preparing";
    downloadBtn.textContent = "Preparing High-Quality Download";
    downloadBtn.disabled = true;
    downloadBtn.classList.remove("ready", "stop");

    showProgress(72, "8.2 MiB/s", "00:19");
    setStatus(
      "High-resolution video is being prepared on the server before the final save step.",
      "info"
    );
  }
}

fetchBtn.addEventListener("click", fetchFormats);
clearBtn.addEventListener("click", () => {
  urlInput.value = "";
  formatsPanel.classList.add("hidden");
  currentData = null;
  playlistTaskId = null;
  playlistTaskSignature = "";
  setElementText(mp3QualityLabel, "MP3 quality");
  stopPreparation();
  resetDownloadButton();
  hideProgress();
  setStatus("", "info");
});

downloadBtn.addEventListener("click", triggerDownload);

clearTempBtn.addEventListener("click", async () => {
  if (!confirm("Are you sure you want to clear all temporary files and active tasks from the server?")) {
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
applyDemoState();
