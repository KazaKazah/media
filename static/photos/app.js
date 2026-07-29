const TREE_STORAGE_KEY = "dropandtag.expandedTree";

function loadExpandedTree() {
  try {
    return new Set(JSON.parse(localStorage.getItem(TREE_STORAGE_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

const state = {
  currentPath: "",
  folders: [],
  files: [],
  tree: [],
  loadingTreePaths: new Set(),
  expandedFolders: loadExpandedTree(),
  selected: null,
  selectedType: "",
  filter: "",
  searchMode: false,
  mediaType: "all",
  sort: "newest",
  searchRequestId: 0,
  fileCount: 0,
  nextOffset: 0,
  hasMore: false,
  currentCover: "",
  loadingMore: false,
  viewerIndex: -1,
  viewerFiles: [],
  pendingUploadItems: [],
  uploading: false,
};

const elements = {
  mediaRoot: document.querySelector("#mediaRoot"),
  tree: document.querySelector("#tree"),
  breadcrumbs: document.querySelector("#mediaBreadcrumbs"),
  folderCount: document.querySelector("#mediaFolderCount"),
  fileCount: document.querySelector("#mediaFileCount"),
  viewToggle: document.querySelector("#mediaViewToggle"),
  typeFilters: [...document.querySelectorAll("[data-media-type]")],
  sort: document.querySelector("#mediaSort"),
  dropTargetName: document.querySelector("#dropTargetName"),
  sidebar: document.querySelector("#mediaSidebar"),
  sidebarOpen: document.querySelector("#mediaSidebarOpen"),
  sidebarClose: document.querySelector("#mediaSidebarClose"),
  sidebarBackdrop: document.querySelector("#mediaSidebarBackdrop"),
  folderRow: document.querySelector("#folderRow"),
  gallery: document.querySelector("#gallery"),
  inspector: document.querySelector("#inspector"),
  search: document.querySelector("#search"),
  refreshTree: document.querySelector("#refreshTree"),
  collapseTree: document.querySelector("#collapseTree"),
  createFolder: document.querySelector("#createFolder"),
  siteImportForm: document.querySelector("#siteImportForm"),
  siteUrl: document.querySelector("#siteUrl"),
  siteImportStatus: document.querySelector("#siteImportStatus"),
  dropZone: document.querySelector("#dropZone"),
  uploadSelectFiles: document.querySelector("#uploadSelectFiles"),
  uploadFileInput: document.querySelector("#uploadFileInput"),
  uploadPreviewPanel: document.querySelector("#uploadPreviewPanel"),
  uploadPreviewGrid: document.querySelector("#uploadPreviewGrid"),
  uploadSummary: document.querySelector("#uploadSummary"),
  uploadTargetLabel: document.querySelector("#uploadTargetLabel"),
  uploadConfirm: document.querySelector("#uploadConfirm"),
  uploadClear: document.querySelector("#uploadClear"),
  viewerModal: document.querySelector("#viewerModal"),
  viewerTitle: document.querySelector("#viewerTitle"),
  viewerPath: document.querySelector("#viewerPath"),
  viewerCounter: document.querySelector("#viewerCounter"),
  viewerBody: document.querySelector("#viewerBody"),
  viewerPrev: document.querySelector("#viewerPrev"),
  viewerNext: document.querySelector("#viewerNext"),
};

let loadMoreObserver = null;

function getCookie(name) {
  return document.cookie
    .split(";")
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith(`${name}=`))
    ?.split("=")[1] || "";
}

function mediaUrl(filePath) {
  return `/media/${filePath.split("/").map(encodeURIComponent).join("/")}`;
}

function thumbnailUrl(filePath, size = "thumb") {
  return `/thumb/${encodeURIComponent(size)}/${filePath.split("/").map(encodeURIComponent).join("/")}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "content-type": "application/json",
      "x-csrftoken": getCookie("csrftoken"),
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Request failed");
  return payload;
}

async function apiForm(path, formData) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "x-csrftoken": getCookie("csrftoken"),
    },
    body: formData,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Request failed");
  return payload;
}

function formatPath(value) {
  return value ? `/${value}` : "/";
}

function formatFileSize(bytes = 0) {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / 1024 ** 2).toFixed(bytes < 10 * 1024 ** 2 ? 1 : 0)} МБ`;
}

function formatModified(timestamp) {
  return timestamp ? new Intl.DateTimeFormat("ru", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(timestamp * 1000)) : "";
}

function renderMediaLocation(label = "") {
  elements.breadcrumbs.replaceChildren();
  if (label) {
    const current = document.createElement("strong");
    current.textContent = label;
    elements.breadcrumbs.append(current);
  } else {
    const root = document.createElement("button");
    root.type = "button";
    root.textContent = "Медиатека";
    root.addEventListener("click", () => loadFolder(""));
    elements.breadcrumbs.append(root);
    let path = "";
    state.currentPath.split("/").filter(Boolean).forEach((part) => {
      path = path ? `${path}/${part}` : part;
      const target = path;
      const divider = document.createElement("span");
      divider.textContent = "›";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = part;
      button.addEventListener("click", () => loadFolder(target));
      elements.breadcrumbs.append(divider, button);
    });
  }
  elements.folderCount.textContent = `${state.folders.length} папок`;
  elements.fileCount.textContent = `${state.fileCount} файлов`;
  elements.dropTargetName.textContent = formatPath(state.currentPath);
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

function escapeAttr(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function dragPayload(type, path) {
  return JSON.stringify({ type, path });
}

function readDragPayload(event) {
  const raw = event.dataTransfer.getData("application/json") || event.dataTransfer.getData("text/plain");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return { type: "file", path: raw };
  }
}

function isUploadableMedia(file) {
  return file.type.startsWith("image/") || file.type.startsWith("video/");
}

function clearPendingUploadFiles() {
  state.pendingUploadItems.forEach((item) => URL.revokeObjectURL(item.url));
  state.pendingUploadItems = [];
  renderUploadPreview();
}

function prepareUploadFiles(files) {
  const mediaFiles = [...files].filter(isUploadableMedia);
  if (!mediaFiles.length) {
    window.alert("Выберите фото или видео файл.");
    return;
  }

  clearPendingUploadFiles();
  state.pendingUploadItems = mediaFiles.map((file) => ({
    file,
    url: URL.createObjectURL(file),
    type: file.type.startsWith("image/") ? "image" : "video",
  }));
  renderUploadPreview();
}

function renderUploadPreview() {
  const hasItems = state.pendingUploadItems.length > 0;
  elements.uploadPreviewPanel.classList.toggle("d-none", !hasItems);
  elements.uploadTargetLabel.textContent = formatPath(state.currentPath);
  elements.uploadConfirm.disabled = !hasItems || state.uploading;
  elements.uploadClear.disabled = state.uploading;
  elements.uploadConfirm.textContent = state.uploading ? "Загружаю..." : "Загрузить";
  elements.uploadPreviewGrid.replaceChildren();

  if (!hasItems) {
    elements.uploadSummary.textContent = "";
    return;
  }

  elements.uploadSummary.textContent = `Выбрано файлов: ${state.pendingUploadItems.length}`;
  state.pendingUploadItems.forEach((item) => {
    const card = document.createElement("article");
    card.className = "upload-preview-card";
    const preview = item.type === "image"
      ? `<img src="${escapeAttr(item.url)}" alt="">`
      : `<video src="${escapeAttr(item.url)}" muted preload="metadata"></video>`;
    card.innerHTML = `
      <span class="upload-preview-thumb">${preview}</span>
      <span class="upload-preview-name" title="${escapeAttr(item.file.name)}">${escapeHtml(item.file.name)}</span>
    `;
    elements.uploadPreviewGrid.appendChild(card);
  });
}

function installDropTarget(element, targetPath) {
  element.addEventListener("dragover", (event) => {
    event.preventDefault();
    element.classList.add("drag-over");
  });
  element.addEventListener("dragleave", () => element.classList.remove("drag-over"));
  element.addEventListener("drop", async (event) => {
    event.preventDefault();
    element.classList.remove("drag-over");
    const payload = readDragPayload(event);
    if (payload?.path) await moveSelected(payload.path, targetPath, payload.type);
  });
}

async function askCreateFolder(parentPath) {
  const name = window.prompt(`Имя новой папки в ${formatPath(parentPath)}`);
  if (!name) return;
  try {
    const created = await api("/api/create-folder/", {
      method: "POST",
      body: JSON.stringify({ parent: parentPath, name }),
    });
    await loadTree();
    await loadFolder(created.path || parentPath);
  } catch (error) {
    window.alert(error.message);
  }
}

function persistExpandedTree() {
  localStorage.setItem(TREE_STORAGE_KEY, JSON.stringify([...state.expandedFolders]));
}

function hasChildren(folder) {
  return Boolean(folder.childCount || folder.children?.length);
}

function isFolderExpanded(path) {
  return path === "" || state.expandedFolders.has(path);
}

function findTreeFolder(path, folders = state.tree) {
  for (const folder of folders) {
    if (folder.path === path) return folder;
    const child = findTreeFolder(path, folder.children || []);
    if (child) return child;
  }
  return null;
}

async function ensureTreeChildren(folder) {
  if (!folder || folder.childrenLoaded || state.loadingTreePaths.has(folder.path)) return;
  state.loadingTreePaths.add(folder.path);
  renderTree();
  try {
    const payload = await api(`/api/tree-children/?path=${encodeURIComponent(folder.path)}`);
    folder.children = payload.folders || [];
    folder.childCount = folder.children.length;
    folder.childrenLoaded = true;
  } catch (error) {
    window.alert(error.message);
  } finally {
    state.loadingTreePaths.delete(folder.path);
  }
}

async function toggleTreeFolder(path) {
  if (state.expandedFolders.has(path)) {
    state.expandedFolders.delete(path);
  } else {
    state.expandedFolders.add(path);
    await ensureTreeChildren(findTreeFolder(path));
  }
  persistExpandedTree();
  renderTree();
}

function expandPath(path, includeSelf = true) {
  const parts = path.split("/").filter(Boolean);
  const limit = includeSelf ? parts.length : parts.length - 1;
  for (let index = 1; index <= limit; index += 1) {
    state.expandedFolders.add(parts.slice(0, index).join("/"));
  }
  persistExpandedTree();
}

function collapseTreeToCurrentPath() {
  state.expandedFolders.clear();
  expandPath(state.currentPath, false);
  renderTree();
}

function renderTreeNode(folder, depth = 0) {
  const row = document.createElement("div");
  row.className = "tree-row";
  row.style.setProperty("--tree-depth", depth);
  const expanded = isFolderExpanded(folder.path);
  const expandable = hasChildren(folder);

  const button = document.createElement("button");
  button.type = "button";
  button.dataset.path = folder.path;
  button.className = `tree-folder ${folder.path === state.currentPath ? "active" : ""}`;
  button.draggable = true;
  button.innerHTML = `
    <span class="tree-toggle ${expanded ? "expanded" : ""}" title="${expandable ? (expanded ? "Свернуть" : "Развернуть") : "Нет вложенных папок"}">${state.loadingTreePaths.has(folder.path) ? "…" : (expandable ? "›" : "")}</span>
    <span class="tree-folder-icon" aria-hidden="true"></span>
    <span class="tree-folder-name" title="${escapeAttr(folder.path)}">${escapeHtml(folder.name)}</span>
    ${expandable ? `<span class="tree-count">${folder.childCount || folder.children?.length || 0}</span>` : ""}
  `;
  button.addEventListener("click", async (event) => {
    if (event.target.closest(".tree-toggle") && expandable) {
      await toggleTreeFolder(folder.path);
      return;
    }
    loadFolder(folder.path);
  });
  button.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("application/json", dragPayload("folder", folder.path));
    event.dataTransfer.effectAllowed = "move";
  });
  installDropTarget(button, folder.path);

  const addButton = document.createElement("button");
  addButton.type = "button";
  addButton.className = "add-folder";
  addButton.title = "Создать подпапку";
  addButton.textContent = "+";
  addButton.addEventListener("click", (event) => {
    event.stopPropagation();
    askCreateFolder(folder.path);
  });

  row.append(button, addButton);
  elements.tree.appendChild(row);
  if (expanded) {
    folder.children.forEach((child) => renderTreeNode(child, depth + 1));
  }
}

function renderTree() {
  elements.tree.replaceChildren();

  const row = document.createElement("div");
  row.className = "tree-row tree-row-root";
  row.style.setProperty("--tree-depth", 0);

  const root = document.createElement("button");
  root.type = "button";
  root.dataset.path = "";
  root.className = `tree-folder ${state.currentPath === "" ? "active" : ""}`;
  root.innerHTML = `
    <span class="tree-toggle expanded">›</span>
    <span class="tree-root-icon" aria-hidden="true">/</span>
    <span class="tree-folder-name">Все фото</span>
    <span class="tree-count">${state.tree.length}</span>
  `;
  root.addEventListener("click", () => loadFolder(""));
  installDropTarget(root, "");

  const addRoot = document.createElement("button");
  addRoot.type = "button";
  addRoot.className = "add-folder";
  addRoot.title = "Создать папку";
  addRoot.textContent = "+";
  addRoot.addEventListener("click", () => askCreateFolder(""));

  row.append(root, addRoot);
  elements.tree.appendChild(row);
  state.tree.forEach((folder) => renderTreeNode(folder));
}

function renderFolders() {
  elements.folderRow.replaceChildren();
  const folders = state.folders.filter(matchesEntryFilter);
  folders.forEach((folder) => {
    const card = document.createElement("article");
    card.className = `folder-card ${state.selectedType === "folder" && state.selected?.path === folder.path ? "active" : ""}`;
    card.draggable = true;
    const cover = folder.cover
      ? `<span class="folder-cover"><img src="${thumbnailUrl(folder.cover, "thumb")}" alt="" loading="lazy" decoding="async"></span>`
      : '<span class="folder-icon" aria-hidden="true"></span>';
    card.innerHTML = `
      <button class="folder-open" type="button" title="Открыть папку">
        ${cover}
        <span class="min-w-0">
          <span class="folder-title">${escapeHtml(folder.name)}</span>
          <span class="folder-path">${escapeHtml(formatPath(folder.path))}</span>
        </span>
      </button>
      <span class="card-actions">
        <button class="folder-select icon-button" type="button" title="Выбрать папку">⋯</button>
        <button class="folder-rename icon-button" type="button" title="Переименовать папку">✎</button>
        <button class="folder-delete icon-button danger" type="button" title="Удалить папку">×</button>
      </span>
    `;
    card.querySelector(".folder-open").addEventListener("click", () => loadFolder(folder.path));
    card.querySelector(".folder-select").addEventListener("click", () => selectFolder(folder));
    card.querySelector(".folder-rename").addEventListener("click", () => {
      selectFolder(folder);
      renameSelected();
    });
    card.querySelector(".folder-delete").addEventListener("click", () => {
      selectFolder(folder);
      deleteSelected();
    });
    card.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("application/json", dragPayload("folder", folder.path));
      event.dataTransfer.effectAllowed = "move";
    });
    installDropTarget(card, folder.path);
    elements.folderRow.appendChild(card);
  });
}

function matchesFilter(file) {
  return matchesEntryFilter(file);
}

function visibleFiles() {
  const files = state.files.filter((file) =>
    matchesFilter(file) && (state.mediaType === "all" || file.type === state.mediaType)
  );
  return files.sort((left, right) => {
    if (state.sort === "name") return left.name.localeCompare(right.name, "ru", { numeric: true });
    if (state.sort === "oldest") return left.modified - right.modified;
    return right.modified - left.modified;
  });
}

function createMediaCard(file, { featured = false } = {}) {
  const card = document.createElement("article");
  card.className = [
    "media-card",
    featured ? "media-card-featured" : "",
    state.selectedType === "file" && state.selected?.path === file.path ? "active" : "",
  ].filter(Boolean).join(" ");
  card.draggable = true;
  card.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("application/json", dragPayload("file", file.path));
    event.dataTransfer.setData("text/plain", file.path);
    event.dataTransfer.effectAllowed = "move";
  });

  const source = mediaUrl(file.path);
  const displaySource = file.type === "image" ? thumbnailUrl(file.path, featured ? "preview" : "thumb") : source;
  const thumb = file.type === "image"
    ? `<img src="${displaySource}" alt="" loading="lazy" decoding="async">`
    : `<video src="${displaySource}" muted preload="metadata"></video>`;
  const tags = file.tags.map((tag) => `<span class="tag-pill">${escapeHtml(tag)}</span>`).join("");
  const badge = featured ? `<span class="cover-badge">Главная обложка</span>` : "";
  card.innerHTML = `
    <button class="media-main" type="button" title="Выбрать файл">
      <span class="thumb">${thumb}</span>
      <span class="media-body">
        ${badge}
        <span class="fw-semibold media-name" title="${escapeAttr(file.name)}">${escapeHtml(file.name)}</span>
        <span class="media-file-meta"><small>${file.type === "video" ? "Видео" : "Фото"}</small><small>${formatFileSize(file.size)}</small><small>${formatModified(file.modified)}</small></span>
        <span class="tag-list mt-2">${tags}</span>
      </span>
    </button>
    <span class="media-actions">
      <button class="icon-button media-open" type="button" title="Открыть">↗</button>
      <button class="icon-button media-rename" type="button" title="Переименовать">✎</button>
      <button class="icon-button danger media-delete" type="button" title="Удалить">×</button>
    </span>
  `;
  card.querySelector(".media-main").addEventListener("click", () => selectFile(file));
  card.querySelector(".media-open").addEventListener("click", () => openViewer(file));
  card.querySelector(".media-rename").addEventListener("click", () => {
    selectFile(file);
    renameSelected();
  });
  card.querySelector(".media-delete").addEventListener("click", () => {
    selectFile(file);
    deleteSelected();
  });
  return card;
}

function renderGallery() {
  loadMoreObserver?.disconnect();
  elements.gallery.replaceChildren();
  const files = visibleFiles();
  if (!files.length) {
    const empty = document.createElement("p");
    empty.className = "text-secondary";
    empty.textContent = "В этой папке нет медиа по текущему фильтру.";
    elements.gallery.appendChild(empty);
    return;
  }

  const coverFile = state.searchMode ? null : files.find((file) => file.path === state.currentCover);
  if (coverFile) {
    elements.gallery.appendChild(createMediaCard(coverFile, { featured: true }));
  }

  files
    .filter((file) => file.path !== coverFile?.path)
    .forEach((file) => {
      elements.gallery.appendChild(createMediaCard(file));
    });

  if (state.hasMore) {
    const more = document.createElement("button");
    more.className = "load-more";
    more.type = "button";
    more.textContent = state.loadingMore
      ? "Загружаю..."
      : `Показать ещё (${Math.max(state.fileCount - state.files.length, 0)})`;
    more.disabled = state.loadingMore;
    more.addEventListener("click", loadMoreFiles);
    elements.gallery.appendChild(more);
    if ("IntersectionObserver" in window) {
      loadMoreObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMoreFiles();
      }, { rootMargin: "320px" });
      loadMoreObserver.observe(more);
    }
  }
}

function allFolderOptions(folders, result = [{ name: "/", path: "" }], depth = 0) {
  folders.forEach((folder) => {
    result.push({ name: `${"  ".repeat(depth)}${folder.name}`, path: folder.path });
    allFolderOptions(folder.children, result, depth + 1);
  });
  return result;
}

function isInsideFolder(path, folderPath) {
  return path === folderPath || path.startsWith(`${folderPath}/`);
}

function matchesEntryFilter(entry) {
  const query = state.filter.trim().toLowerCase();
  if (!query || state.searchMode) return true;
  const tags = entry.tags || [];
  return entry.name.toLowerCase().includes(query)
    || entry.path.toLowerCase().includes(query)
    || tags.some((tag) => tag.toLowerCase().includes(query));
}

function destinationOptions(selectedPath = "", selectedType = "") {
  return allFolderOptions(state.tree)
    .filter((folder) => selectedType !== "folder" || !isInsideFolder(folder.path, selectedPath))
    .map((folder) => `<option value="${escapeAttr(folder.path)}">${escapeHtml(folder.name)}</option>`)
    .join("");
}

function selectFile(file) {
  state.selected = file;
  state.selectedType = "file";
  renderFolders();
  renderGallery();
  renderInspector();
}

function selectFolder(folder) {
  state.selected = folder;
  state.selectedType = "folder";
  renderFolders();
  renderGallery();
  renderInspector();
}

function renderViewer(file) {
  const source = file.type === "image" ? thumbnailUrl(file.path, "preview") : mediaUrl(file.path);
  elements.viewerTitle.textContent = file.name;
  elements.viewerPath.textContent = formatPath(file.path);
  elements.viewerCounter.textContent = state.viewerFiles.length
    ? ` · ${state.viewerIndex + 1} / ${state.viewerFiles.length}${state.hasMore ? "+" : ""}`
    : "";
  elements.viewerBody.innerHTML = file.type === "image"
    ? `<img src="${source}" alt="${escapeAttr(file.name)}">`
    : `<video src="${source}" controls autoplay></video>`;
  const canMove = state.viewerFiles.length > 1 || state.hasMore;
  elements.viewerPrev.disabled = !canMove;
  elements.viewerNext.disabled = !canMove;
}

function openViewer(file) {
  state.viewerFiles = visibleFiles();
  state.viewerIndex = Math.max(state.viewerFiles.findIndex((item) => item.path === file.path), 0);
  renderViewer(state.viewerFiles[state.viewerIndex] || file);
  bootstrap.Modal.getOrCreateInstance(elements.viewerModal).show();
}

async function stepViewer(direction) {
  if (!state.viewerFiles.length) return;
  if (direction > 0 && state.viewerIndex === state.viewerFiles.length - 1 && state.hasMore) {
    await loadMoreFiles({ quiet: true });
    state.viewerFiles = visibleFiles();
  }
  state.viewerIndex = (state.viewerIndex + direction + state.viewerFiles.length) % state.viewerFiles.length;
  renderViewer(state.viewerFiles[state.viewerIndex]);
}

function renderInspector(status = "") {
  if (!state.selected) {
    elements.inspector.innerHTML = `
      <div class="p-4">
        <h3 class="h5">Выберите элемент</h3>
        <p class="text-secondary mb-0">Фото можно открыть, тегировать, переименовать, перенести или удалить. Папку можно выбрать кнопкой ⋯.</p>
      </div>
    `;
    return;
  }

  if (state.selectedType === "folder") {
    renderFolderInspector(status);
    return;
  }

  const file = state.selected;
  const preview = file.type === "image"
    ? `<img src="${thumbnailUrl(file.path, "preview")}" alt="">`
    : `<video src="${mediaUrl(file.path)}" controls></video>`;
  const options = destinationOptions(file.path, "file");

  elements.inspector.innerHTML = `
    <button class="preview p-0 border-0 w-100" id="openViewer" type="button" title="Открыть крупный просмотр">${preview}</button>
    <div class="p-3">
      <h3 class="h5 mb-1">${escapeHtml(file.name)}</h3>
      <p class="text-secondary file-path">${escapeHtml(formatPath(file.path))}</p>
      <div class="action-grid mb-3">
        <button class="btn btn-outline-primary" id="openViewerButton" type="button">Открыть</button>
        <button class="btn btn-outline-dark" id="renameEntry" type="button">Переименовать</button>
        <button class="btn btn-outline-success" id="setCoverButton" type="button">Обложка</button>
        <button class="btn btn-outline-danger" id="deleteEntry" type="button">Удалить</button>
      </div>
      <label class="form-label" for="tagInput">Теги через запятую</label>
      <input class="form-control" id="tagInput" value="${escapeAttr(file.tags.join(", "))}">
      <button class="btn btn-outline-secondary w-100 mt-2" id="saveTags" type="button">Сохранить теги</button>
      <label class="form-label mt-3" for="moveTarget">Папка назначения</label>
      <select class="form-select" id="moveTarget">${options}</select>
      <button class="btn btn-success w-100 mt-2" id="moveFile" type="button">Перенести</button>
      <p class="small text-secondary mb-0 mt-3" id="status">${escapeHtml(status)}</p>
    </div>
  `;

  document.querySelector("#openViewer").addEventListener("click", () => openViewer(file));
  document.querySelector("#openViewerButton").addEventListener("click", () => openViewer(file));
  document.querySelector("#setCoverButton").addEventListener("click", () => setCurrentFolderCover(file));
  document.querySelector("#renameEntry").addEventListener("click", () => renameSelected());
  document.querySelector("#deleteEntry").addEventListener("click", () => deleteSelected());
  document.querySelector("#saveTags").addEventListener("click", saveTags);
  document.querySelector("#moveFile").addEventListener("click", async () => {
    await moveSelected(file.path, document.querySelector("#moveTarget").value, "file");
  });
}

function renderFolderInspector(status = "") {
  const folder = state.selected;
  const options = destinationOptions(folder.path, "folder");
  elements.inspector.innerHTML = `
    <div class="folder-preview">
      <span class="folder-icon" aria-hidden="true"></span>
    </div>
    <div class="p-3">
      <h3 class="h5 mb-1">${escapeHtml(folder.name)}</h3>
      <p class="text-secondary file-path">${escapeHtml(formatPath(folder.path))}</p>
      <div class="action-grid mb-3">
        <button class="btn btn-outline-primary" id="openFolderButton" type="button">Открыть</button>
        <button class="btn btn-outline-dark" id="renameEntry" type="button">Переименовать</button>
        <button class="btn btn-outline-danger" id="deleteEntry" type="button">Удалить</button>
      </div>
      <label class="form-label" for="moveTarget">Папка назначения</label>
      <select class="form-select" id="moveTarget">${options}</select>
      <button class="btn btn-success w-100 mt-2" id="moveFolder" type="button">Перенести папку</button>
      <p class="small text-secondary mb-0 mt-3" id="status">${escapeHtml(status)}</p>
    </div>
  `;

  document.querySelector("#openFolderButton").addEventListener("click", () => loadFolder(folder.path));
  document.querySelector("#renameEntry").addEventListener("click", () => renameSelected());
  document.querySelector("#deleteEntry").addEventListener("click", () => deleteSelected());
  document.querySelector("#moveFolder").addEventListener("click", async () => {
    await moveSelected(folder.path, document.querySelector("#moveTarget").value, "folder");
  });
}

async function saveTags() {
  if (!state.selected) return;
  try {
    const tags = document.querySelector("#tagInput").value.split(",");
    const updated = await api("/api/tags/", {
      method: "POST",
      body: JSON.stringify({ path: state.selected.path, tags }),
    });
    state.selected.tags = updated.tags;
    const file = state.files.find((item) => item.path === state.selected.path);
    if (file) file.tags = updated.tags;
    renderGallery();
    renderInspector("Теги сохранены");
  } catch (error) {
    window.alert(error.message);
  }
}

async function setCurrentFolderCover(file) {
  try {
    await api("/api/cover/", {
      method: "POST",
      body: JSON.stringify({ folder: state.currentPath, cover: file.path }),
    });
    state.currentCover = file.path;
    await loadTree();
    renderTree();
    renderGallery();
    renderInspector("Обложка папки обновлена");
  } catch (error) {
    window.alert(error.message);
  }
}

async function renameSelected() {
  if (!state.selected || !state.selectedType) return;
  const currentName = state.selected.name;
  const nextName = window.prompt("Новое имя", currentName);
  if (!nextName || nextName === currentName) return;

  try {
    const renamed = await api("/api/rename/", {
      method: "POST",
      body: JSON.stringify({
        path: state.selected.path,
        name: nextName,
        type: state.selectedType,
      }),
    });
    const nextType = state.selectedType;
    await loadTree();
    const folderToLoad = nextType === "folder" && state.currentPath === state.selected.path
      ? renamed.to
      : state.currentPath;
    await loadFolder(folderToLoad, false);
    const collection = nextType === "folder" ? state.folders : state.files;
    const refreshed = collection.find((item) => item.path === renamed.to);
    if (refreshed) {
      state.selected = refreshed;
      state.selectedType = nextType;
      renderFolders();
      renderGallery();
      renderInspector(`Переименовано: ${renamed.name}`);
    }
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteSelected() {
  if (!state.selected || !state.selectedType) return;
  const label = state.selectedType === "folder" ? "папку" : "файл";
  const confirmed = window.confirm(`Удалить ${label} "${state.selected.name}"? Это действие нельзя отменить.`);
  if (!confirmed) return;

  try {
    const deletedPath = state.selected.path;
    const deletedType = state.selectedType;
    await api("/api/delete/", {
      method: "POST",
      body: JSON.stringify({ path: deletedPath, type: deletedType }),
    });
    state.selected = null;
    state.selectedType = "";
    await loadTree();
    if (deletedType === "folder" && isInsideFolder(state.currentPath, deletedPath)) {
      const parent = deletedPath.split("/").slice(0, -1).join("/");
      await loadFolder(parent, false);
    } else {
      await loadFolder(state.currentPath, false);
    }
    renderInspector("Удалено");
  } catch (error) {
    window.alert(error.message);
  }
}

async function moveSelected(source, targetFolder, type = "file") {
  try {
    const moved = await api("/api/move/", {
      method: "POST",
      body: JSON.stringify({ source, targetFolder, type }),
    });
    if (state.selected?.path === source) {
      state.selected = null;
      state.selectedType = "";
    }
    await loadTree();
    try {
      await loadFolder(state.currentPath, false);
    } catch {
      await loadFolder(targetFolder, false);
    }
    renderInspector(`Перенесено: ${formatPath(moved.to)}`);
  } catch (error) {
    window.alert(error.message);
  }
}

async function uploadFiles(files, targetFolder) {
  const mediaFiles = [...files].filter(isUploadableMedia);
  if (!mediaFiles.length) {
    window.alert("Выберите фото или видео файл.");
    return false;
  }

  try {
    const formData = new FormData();
    formData.append("targetFolder", targetFolder);
    mediaFiles.forEach((file) => formData.append("files", file));
    const result = await apiForm("/api/upload/", formData);
    await loadTree();
    await loadFolder(targetFolder, false);
    const skipped = result.skipped?.length ? ` Пропущено: ${result.skipped.length}.` : "";
    renderInspector(`Загружено: ${result.saved.length}.${skipped}`);
    return true;
  } catch (error) {
    window.alert(error.message);
    return false;
  }
}

async function uploadPendingFiles() {
  if (!state.pendingUploadItems.length || state.uploading) return;
  state.uploading = true;
  renderUploadPreview();
  try {
    const uploaded = await uploadFiles(state.pendingUploadItems.map((item) => item.file), state.currentPath);
    if (uploaded) clearPendingUploadFiles();
  } finally {
    state.uploading = false;
    renderUploadPreview();
  }
}

async function importSiteImages(event) {
  event.preventDefault();
  const url = elements.siteUrl.value.trim();
  if (!url) return;
  const button = elements.siteImportForm.querySelector("button");
  button.disabled = true;
  elements.siteImportStatus.textContent = "Ищу и скачиваю изображения...";
  try {
    const result = await api("/api/import-site/", {
      method: "POST",
      body: JSON.stringify({
        targetFolder: state.currentPath,
        url,
      }),
    });
    await loadTree();
    await loadFolder(result.folder, false);
    const skipped = result.skipped?.length ? ` Пропущено: ${result.skipped.length}.` : "";
    const old = result.skippedExisting ? ` Уже были скачаны: ${result.skippedExisting}.` : "";
    const galleries = result.galleryCount ? ` Галерей: ${result.galleryCount}.` : "";
    elements.siteImportStatus.textContent = `Создана папка ${formatPath(result.folder)}.${galleries} Найдено фото: ${result.found}. Скачано: ${result.saved.length}.${old}${skipped}`;
    renderInspector(`Импортировано с сайта: ${result.saved.length}`);
  } catch (error) {
    elements.siteImportStatus.textContent = error.message;
    window.alert(error.message);
  } finally {
    button.disabled = false;
  }
}

async function loadTree() {
  const payload = await api("/api/tree/");
  state.tree = payload.folders;
  renderTree();
}

function applyFolderPayload(payload, append = false) {
  state.currentPath = payload.path;
  state.folders = payload.folders;
  state.files = append ? [...state.files, ...payload.files] : payload.files;
  state.fileCount = payload.fileCount || state.files.length;
  state.nextOffset = payload.nextOffset || state.files.length;
  state.hasMore = Boolean(payload.hasMore);
  state.currentCover = append ? state.currentCover : (payload.cover || "");
  renderMediaLocation();
  renderUploadPreview();
}

async function loadFolder(folderPath = "", updateTree = true) {
  state.searchMode = false;
  const payload = await api(`/api/folder/?path=${encodeURIComponent(folderPath)}`);
  applyFolderPayload(payload);
  expandPath(state.currentPath);
  state.selected = null;
  state.selectedType = "";
  renderFolders();
  renderGallery();
  renderInspector();
  if (updateTree) renderTree();
  document.body.classList.remove("media-sidebar-open");
}

function applySearchPayload(payload) {
  state.searchMode = true;
  state.currentCover = "";
  state.folders = payload.folders || [];
  state.files = payload.files || [];
  state.fileCount = payload.fileCount || state.files.length;
  state.nextOffset = state.files.length;
  state.hasMore = false;
  state.selected = null;
  state.selectedType = "";
  renderMediaLocation(`Поиск: ${payload.query || state.filter.trim()}`);
  renderFolders();
  renderGallery();
  renderInspector(
    `Найдено: папок ${payload.folderCount || state.folders.length}, файлов ${state.fileCount}.`
  );
}

async function searchMedia(query) {
  const requestId = state.searchRequestId + 1;
  state.searchRequestId = requestId;
  if (!query) {
    await loadFolder(state.currentPath, false);
    return;
  }
  try {
    const payload = await api(`/api/search/?q=${encodeURIComponent(query)}`);
    if (requestId !== state.searchRequestId) return;
    applySearchPayload(payload);
  } catch (error) {
    window.alert(error.message);
  }
}

function debounce(callback, delay = 250) {
  let timeoutId = 0;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => callback(...args), delay);
  };
}

async function loadMoreFiles(options = {}) {
  if (state.loadingMore || !state.hasMore) return;
  state.loadingMore = true;
  if (!options.quiet) renderGallery();
  try {
    const payload = await api(
      `/api/folder/?path=${encodeURIComponent(state.currentPath)}&offset=${state.nextOffset}`
    );
    applyFolderPayload(payload, true);
    if (!options.quiet) {
      renderFolders();
      renderGallery();
    }
  } catch (error) {
    window.alert(error.message);
  } finally {
    state.loadingMore = false;
    if (!options.quiet) renderGallery();
  }
}

async function boot() {
  const compact = localStorage.getItem("dropandtag.compactView") === "1";
  document.body.classList.toggle("media-compact-view", compact);
  elements.viewToggle.textContent = compact ? "Крупно" : "Компактно";
  const config = await api("/api/config/");
  elements.mediaRoot.textContent = config.mediaRoot;
  await loadTree();
  const initialPath = new URLSearchParams(window.location.search).get("path") || "";
  await loadFolder(initialPath);
}

const runMediaSearch = debounce(searchMedia);

elements.search.addEventListener("input", (event) => {
  state.filter = event.target.value;
  runMediaSearch(state.filter.trim());
});

elements.refreshTree.addEventListener("click", async () => {
  await loadTree();
  await loadFolder(state.currentPath);
});

elements.collapseTree.addEventListener("click", collapseTreeToCurrentPath);
elements.createFolder.addEventListener("click", () => askCreateFolder(state.currentPath));
elements.typeFilters.forEach((button) => button.addEventListener("click", () => {
  state.mediaType = button.dataset.mediaType;
  elements.typeFilters.forEach((item) => item.classList.toggle("active", item === button));
  renderGallery();
}));
elements.sort.addEventListener("change", () => {
  state.sort = elements.sort.value;
  renderGallery();
});
const toggleSidebar = (open) => document.body.classList.toggle("media-sidebar-open", open);
elements.sidebarOpen.addEventListener("click", () => toggleSidebar(true));
elements.sidebarClose.addEventListener("click", () => toggleSidebar(false));
elements.sidebarBackdrop.addEventListener("click", () => toggleSidebar(false));
elements.viewToggle.addEventListener("click", () => {
  const compact = document.body.classList.toggle("media-compact-view");
  localStorage.setItem("dropandtag.compactView", compact ? "1" : "0");
  elements.viewToggle.textContent = compact ? "Крупно" : "Компактно";
});
elements.siteImportForm.addEventListener("submit", importSiteImages);
elements.uploadSelectFiles.addEventListener("click", () => elements.uploadFileInput.click());
elements.uploadFileInput.addEventListener("change", (event) => {
  prepareUploadFiles(event.target.files);
  event.target.value = "";
});
elements.uploadConfirm.addEventListener("click", uploadPendingFiles);
elements.uploadClear.addEventListener("click", clearPendingUploadFiles);
elements.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.dropZone.classList.add("drag-over");
});
elements.dropZone.addEventListener("dragleave", () => elements.dropZone.classList.remove("drag-over"));
elements.dropZone.addEventListener("drop", async (event) => {
  event.preventDefault();
  elements.dropZone.classList.remove("drag-over");
  if (event.dataTransfer.files?.length) {
    prepareUploadFiles(event.dataTransfer.files);
    return;
  }
  const payload = readDragPayload(event);
  if (payload?.path) await moveSelected(payload.path, state.currentPath, payload.type);
});

elements.viewerModal.addEventListener("hidden.bs.modal", () => {
  elements.viewerBody.innerHTML = "";
  state.viewerIndex = -1;
  state.viewerFiles = [];
});

elements.viewerPrev.addEventListener("click", async () => stepViewer(-1));
elements.viewerNext.addEventListener("click", async () => stepViewer(1));

window.addEventListener("keydown", async (event) => {
  if (event.key === "Escape") document.body.classList.remove("media-sidebar-open");
  if (state.viewerIndex < 0) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    await stepViewer(-1);
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    await stepViewer(1);
  }
});

window.addEventListener("beforeunload", clearPendingUploadFiles);

boot().catch((error) => {
  document.body.innerHTML = `<main class="container py-5"><h1>Ошибка запуска</h1><p>${escapeHtml(error.message)}</p></main>`;
});
