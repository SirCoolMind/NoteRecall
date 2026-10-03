// Inline title editing, shared by the Home schedule rows and the meeting header.
// Spread into an Alpine.data() object. The host component supplies two methods:
//   applyTitle(id, title)  show a title right away (also used to roll it back on failure)
//   titleSaved()           called after the save attempt settles
// The edit saves on Enter or blur, and Esc cancels.
export function titleEditing() {
  return {
    editing: null,   // id of the meeting whose title is being edited
    draft: "",

    startEdit(id, title) {
      this.editing = id;
      this.draft = title;
    },
    returnFocus(id) {
      // The same id can exist on Home (hidden) and in the meeting header; focus the one on screen.
      this.$nextTick(() => {
        const buttons = [...document.querySelectorAll(`[data-edit-for="${id}"]`)];
        (buttons.find((b) => b.offsetParent !== null) || buttons[0])?.focus();
      });
    },
    cancelEdit(id) {
      this.editing = null;
      this.returnFocus(id);
    },
    async commitEdit(id, original, viaKey = false) {
      if (this.editing !== id) return;   // Esc or Enter already settled this edit
      this.editing = null;
      if (viaKey) this.returnFocus(id);
      const title = this.draft.trim();
      if (!title || title === original) return;
      this.applyTitle(id, title);          // optimistic; the next load confirms
      try {
        const res = await fetch(`/api/meetings/${id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
        });
        if (!res.ok) throw new Error(String(res.status));
      } catch (e) {
        this.applyTitle(id, original);
      }
      this.titleSaved();
    },
  };
}
