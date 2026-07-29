(() => {
  const dialogs = [...document.querySelectorAll("dialog.app-modal")];
  if (!dialogs.length) return;

  let savedScroll = 0;

  const lockPage = () => {
    if (document.body.classList.contains("app-modal-open")) return;
    savedScroll = window.scrollY;
    document.body.style.top = `-${savedScroll}px`;
    document.body.classList.add("app-modal-open");
  };

  const unlockPage = () => {
    if (document.querySelector("dialog.app-modal[open]")) return;
    document.body.classList.remove("app-modal-open");
    document.body.style.top = "";
    window.scrollTo(0, savedScroll);
  };

  const openDialog = (dialog) => {
    if (!dialog || dialog.open) return;
    lockPage();
    dialog.showModal();
    requestAnimationFrame(() => dialog.querySelector("input:not([type=hidden]), select, textarea")?.focus({ preventScroll: true }));
  };

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-modal-open]");
    if (opener) {
      event.preventDefault();
      openDialog(document.getElementById(opener.dataset.modalOpen));
      return;
    }

    const closer = event.target.closest("[data-modal-close]");
    if (closer) closer.closest("dialog")?.close();
  });

  dialogs.forEach((dialog) => {
    dialog.addEventListener("close", unlockPage);
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    if (dialog.dataset.autoOpen === "true") openDialog(dialog);
  });
})();
