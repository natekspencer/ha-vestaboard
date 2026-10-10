// Vestaboard composer panel for Home Assistant.
//
// Draws each Vestaboard, virtual Vestaboard or Note array as a grid of bits in
// its own colors, lets you type and paint a message, and sends it with the
// vestaboard.message action as raw character codes.

const HEART_CODE = 62;
const BLANK_CODE = 0;
const COLOR_CODES = [63, 64, 65, 66, 67, 68, 69, 70, 71];
const PALETTE = [63, 64, 65, 66, 67, 68, 69, 70, HEART_CODE];
// What each palette entry inserts into a text message. White and black swap on
// white boards, so they use their codes rather than ⬜ and ⬛.
const TEXT_TOKENS = {
  63: "🟥",
  64: "🟧",
  65: "🟨",
  66: "🟩",
  67: "🟦",
  68: "🟪",
  69: "{69}",
  70: "{70}",
};
const COLOR_NAMES = {
  "#DA291C": "Red",
  "#FA7400": "Orange",
  "#FCB81B": "Yellow",
  "#1F9A44": "Green",
  "#2083D5": "Blue",
  "#702F8A": "Violet",
  "#FFFFFF": "White",
  "#000000": "Black",
  "#141414": "Black",
};
const TOOLS = [
  { id: "type", label: "Type", icon: "mdi:format-text" },
  { id: "pen", label: "Pen", icon: "mdi:pencil" },
  { id: "fill", label: "Fill", icon: "mdi:format-color-fill" },
  { id: "eraser", label: "Eraser", icon: "mdi:eraser" },
];
const TRANSITIONS = [
  ["", "Board default"],
  ["classic", "Classic (all-at-once)"],
  ["column", "Wave (left-to-right)"],
  ["reverse-column", "Drift (right-to-left)"],
  ["edges-to-center", "Curtain (outside-in)"],
  ["row", "Row (top-to-bottom)"],
  ["diagonal", "Diagonal"],
  ["random", "Random bits"],
];
// Horizontal (justify) and vertical (align) text alignment: value, label, icon
const JUSTIFY = [
  ["left", "Left", "mdi:format-align-left"],
  ["center", "Center", "mdi:format-align-center"],
  ["right", "Right", "mdi:format-align-right"],
  ["justified", "Justified", "mdi:format-align-justify"],
];
const ALIGN = [
  ["top", "Top", "mdi:format-vertical-align-top"],
  ["center", "Center", "mdi:format-vertical-align-center"],
  ["bottom", "Bottom", "mdi:format-vertical-align-bottom"],
  ["justified", "Justified", "mdi:distribute-vertical-center"],
];

// Largest and smallest bit width, in pixels
const MAX_BIT_WIDTH = 44;
const MIN_BIT_WIDTH = 6;
const LOGO_TEXT = "VESTABOARD";

const FONT_FAMILY = "VestaboardComposer";
const DRAFT_PREFIX = "vestaboard-composer:";
const LAYOUT_DELAY_MS = 250;

const STYLE = `
  :host {
    display: block;
    min-height: 100%;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--header-height, 56px);
    padding: 0 12px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    font-size: 20px;
    box-sizing: border-box;
  }
  .toolbar .title { flex: 1; }
  main {
    max-width: 1280px;
    margin: 0 auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    box-sizing: border-box;
  }
  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    padding: 16px;
  }
  .editor { display: flex; flex-direction: column; gap: 12px; }
  .editor .modes { align-self: flex-start; }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 16px;
  }
  .spacer { flex: 1; }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--secondary-text-color);
  }
  /* Keeps notes beside a field centered on the field, not its label */
  .field .inline {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 16px;
  }
  select, input[type="number"], textarea.message {
    font: inherit;
    font-size: 14px;
    color: var(--primary-text-color);
    background: var(--input-fill-color, var(--secondary-background-color, #f5f5f5));
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    border-radius: 8px;
    padding: 8px 10px;
  }
  select { min-width: 160px; }
  textarea.message {
    width: 100%;
    min-height: 96px;
    resize: vertical;
    box-sizing: border-box;
    text-transform: uppercase;
  }
  button {
    font: inherit;
    font-size: 14px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border-radius: 18px;
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    background: transparent;
    color: var(--primary-text-color);
    padding: 6px 14px;
    cursor: pointer;
    min-height: 36px;
  }
  button:hover:not(:disabled):not(.selected):not(.primary) {
    background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
  }
  button.selected:hover, button.primary:hover:not(:disabled) { filter: brightness(1.1); }
  button:disabled { opacity: 0.4; cursor: default; }
  button.selected {
    background: var(--primary-color);
    border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
  }
  button.primary {
    background: var(--primary-color);
    border-color: var(--primary-color);
    color: var(--text-primary-color, #fff);
    padding: 6px 22px;
  }
  button.icon { padding: 6px 10px; }
  ha-icon { --mdc-icon-size: 20px; }
  .segmented { display: inline-flex; }
  .segmented button { border-radius: 0; margin-left: -1px; }
  .segmented button:first-child { border-radius: 18px 0 0 18px; margin-left: 0; }
  .segmented button:last-child { border-radius: 0 18px 18px 0; }
  .palette { display: flex; flex-wrap: wrap; gap: 6px; }
  .swatch {
    width: 30px;
    height: 36px;
    border-radius: 6px;
    border: 2px solid transparent;
    padding: 3px;
    box-sizing: border-box;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
  }
  .swatch .chip {
    width: 100%;
    height: 100%;
    border-radius: 3px;
    box-shadow: inset 0 0 0 1px rgba(128, 128, 128, 0.5);
  }
  .swatch.selected { border-color: var(--primary-color); }
  .stage {
    display: flex;
    justify-content: center;
    padding: 8px 0;
    overflow: hidden;
  }
  /* Boards are laid out at their physical size, like the board image */
  .boards {
    display: grid;
    gap: var(--board-gap);
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
    outline: none;
  }
  .board {
    position: relative;
    display: grid;
    align-content: start;
    column-gap: var(--gap-x);
    row-gap: var(--gap-y);
    box-sizing: border-box;
  }
  /* With a frame: each board has its outline, frame and logo. Without one, an
     array is one continuous board, and each Note's color runs to the middle
     of the gap between Notes */
  .board.framed {
    width: var(--board-w);
    height: var(--board-h);
    border: var(--outline) solid var(--outline-color);
    padding: var(--frame-border);
  }
  .logo {
    position: absolute;
    left: 0;
    right: 0;
    bottom: var(--logo-bottom);
    text-align: center;
    font-family: ${FONT_FAMILY}, var(--paper-font-body1_-_font-family, sans-serif);
    font-size: var(--logo-size);
    line-height: normal;
    white-space: nowrap;
    pointer-events: none;
  }
  .bit {
    position: relative;
    width: var(--bit);
    height: var(--bit-h);
    border-radius: calc(var(--bit) * 0.06);
    display: flex;
    align-items: center;
    justify-content: center;
    /* Sized and centered like the board image, so characters are as tall as
       the color and heart fills and line up with them */
    font-family: ${FONT_FAMILY}, var(--paper-font-body1_-_font-family, sans-serif);
    font-size: calc(var(--bit-h) * 0.79);
    line-height: normal;
    overflow: hidden;
  }
  .bit .fill {
    position: absolute;
    left: 2%;
    top: 12%;
    width: 96%;
    height: 62.2%;
  }
  /* The heart image is drawn on a flap with its own flap line. Like the board
     image, it spans the bit's width from the top of the character area */
  .bit .heart {
    position: absolute;
    left: 0;
    top: 12%;
    width: 100%;
    height: auto;
  }
  .swatch img { width: 100%; height: 100%; object-fit: contain; }
  /* The font draws the split flap line through characters; colors need one */
  .bit.color::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: 43%;
    height: max(1px, 2%);
    background: var(--stripe-color);
  }
  .bit.cursor { box-shadow: 0 0 0 2px var(--primary-color); animation: blink 1s steps(2) infinite; }
  @keyframes blink { 50% { box-shadow: 0 0 0 2px transparent; } }
  .boards.tool-pen .bit, .boards.tool-eraser .bit, .boards.tool-fill .bit { cursor: crosshair; }
  .boards.tool-type .bit { cursor: text; }
  .keys {
    position: absolute;
    left: -9999px;
    width: 1px;
    height: 1px;
    opacity: 0;
  }
  .hint { font-size: 13px; color: var(--secondary-text-color); }
  .status { font-size: 14px; }
  .status.error { color: var(--error-color, #db4437); }
  .status.warning { color: var(--warning-color, #ffa600); }
  .status.success { color: var(--success-color, #43a047); }
  .empty { text-align: center; padding: 48px 16px; color: var(--secondary-text-color); }
  .check { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
  .hidden { display: none !important; }
`;

function ensureFont(url) {
  if (!url || document.getElementById("vestaboard-composer-font")) return;
  const style = document.createElement("style");
  style.id = "vestaboard-composer-font";
  // Fonts declared inside a shadow root aren't loaded, so declare it on the page
  style.textContent = `@font-face { font-family: ${FONT_FAMILY}; src: url("${url}") format("opentype"); font-display: block; }`;
  document.head.appendChild(style);
}

function blankGrid(rows, columns) {
  return Array.from({ length: rows }, () => new Array(columns).fill(BLANK_CODE));
}

function copyGrid(grid) {
  return grid.map((row) => row.slice());
}

function sameGrid(a, b) {
  return (
    Array.isArray(a) &&
    Array.isArray(b) &&
    a.length === b.length &&
    a.every((row, r) => row.length === b[r].length && row.every((code, c) => code === b[r][c]))
  );
}

function isBlank(grid) {
  return grid.every((row) => row.every((code) => code === BLANK_CODE));
}

function sameSize(grid, rows, columns) {
  return (
    Array.isArray(grid) &&
    grid.length === rows &&
    grid.every((row) => Array.isArray(row) && row.length === columns)
  );
}

function readDraft(deviceId) {
  try {
    const raw = window.localStorage.getItem(DRAFT_PREFIX + deviceId);
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null;
  }
}

function writeDraft(deviceId, draft) {
  try {
    window.localStorage.setItem(DRAFT_PREFIX + deviceId, JSON.stringify(draft));
  } catch (err) {
    // Drafts are a convenience; ignore storage that's full or blocked
  }
}

class VestaboardComposerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._panel = null;
    this._loaded = false;
    this._boards = [];
    this._themes = {};
    this._charCodes = new Map();
    this._symbols = [];
    this._board = null;
    this._grid = [];
    this._history = [];
    this._future = [];
    this._lastAction = null;
    this._tool = "type";
    this._code = 63;
    this._cursor = { row: 0, column: 0 };
    this._lineStart = 0;
    this._mode = "visual";
    this._text = "";
    this._justify = "center";
    this._align = "center";
    this._textPushed = false;
    // The grid the text was last laid out as, to tell if the board still
    // shows the text
    this._textGrid = null;
    this._painting = false;
    this._layoutTimer = null;
    this._layoutRequest = 0;
    this._cells = [];
    this._onShortcut = this._onShortcut.bind(this);
  }

  set hass(hass) {
    this._hass = hass;
    if (this._menuButton) this._menuButton.hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._render();
      this._loadBoards();
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.narrow = narrow;
  }

  set panel(panel) {
    this._panel = panel;
    ensureFont(panel?.config?.font_url);
  }

  connectedCallback() {
    if (!this._resizeObserver) {
      this._resizeObserver = new ResizeObserver(() => this._sizeBoard());
    }
    if (this._stage) this._resizeObserver.observe(this._stage);
    // Listen on the window so shortcuts work even when nothing has focus
    window.addEventListener("keydown", this._onShortcut);
  }

  disconnectedCallback() {
    this._resizeObserver?.disconnect();
    window.removeEventListener("keydown", this._onShortcut);
  }

  // ---- Data -------------------------------------------------------------

  async _loadBoards(keepSelection = false) {
    let result;
    try {
      result = await this._hass.callWS({ type: "vestaboard/boards" });
    } catch (err) {
      this._setStatus(`Couldn't load your Vestaboards: ${err.message || err}`, "error");
      return;
    }
    this._themes = result.themes;
    this._symbols = result.characters;
    this._heartImage = result.heart_image;
    this._bitSize = result.bit;
    this._charCodes = new Map();
    result.characters.forEach((symbol, code) => {
      if (symbol.trim() && !this._charCodes.has(symbol)) this._charCodes.set(symbol, code);
    });
    this._charCodes.set(" ", BLANK_CODE);
    this._charCodes.set("❤", HEART_CODE);
    this._charCodes.set("♥", HEART_CODE);

    const previous = this._board?.device_id;
    this._boards = result.boards;
    this._renderBoardPicker();
    if (!this._boards.length) {
      this._board = null;
      this._showEmpty(true);
      return;
    }
    this._showEmpty(false);
    const board =
      this._boards.find((b) => b.device_id === previous) || this._boards[0];
    if (keepSelection && previous === board.device_id) {
      this._board = board;
      this._picker.value = board.device_id;
      this._updateBoardNotes();
      this._renderPalette();
      return;
    }
    this._selectBoard(board.device_id);
  }

  _selectBoard(deviceId) {
    const board = this._boards.find((b) => b.device_id === deviceId);
    if (!board) return;
    this._board = board;
    this._history = [];
    this._future = [];
    this._lastAction = null;
    this._textPushed = false;
    this._textGrid = null;

    const draft = readDraft(deviceId);
    if (draft && sameSize(draft.grid, board.rows, board.columns)) {
      this._grid = draft.grid;
      this._text = draft.text || "";
      this._justify = draft.justify || "center";
      this._align = draft.align || "center";
    } else {
      this._grid = copyGrid(board.characters);
      this._text = "";
    }
    this._cursor = { row: 0, column: 0 };
    this._lineStart = 0;
    this._picker.value = deviceId;
    this._messageInput.value = this._text;
    this._renderAlignment();
    this._buildBoard();
    this._renderPalette();
    this._updateBoardNotes();
    this._updateHistoryButtons();
    this._setStatus("");
    if (this._mode === "text") this._syncText();
  }

  _saveDraft() {
    if (!this._board) return;
    writeDraft(this._board.device_id, {
      grid: this._grid,
      text: this._text,
      justify: this._justify,
      align: this._align,
    });
  }

  _themeAt(row, column) {
    const board = this._board;
    const color =
      board.colors[Math.floor(row / board.board_rows)][
        Math.floor(column / board.board_columns)
      ];
    return this._themes[color];
  }

  // ---- Rendering --------------------------------------------------------

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${STYLE}</style>
      <div class="toolbar">
        <span class="menu"></span>
        <span class="title">Vestaboard Composer</span>
      </div>
      <main>
        <div class="empty hidden">
          No Vestaboards are loaded. Add a Vestaboard, a virtual Vestaboard or a
          Note array in Settings &gt; Devices &amp; services to start composing.
        </div>
        <div class="composer">
          <div class="card">
            <div class="row">
              <div class="field">
                <label for="picker">Vestaboard</label>
                <div class="inline">
                  <select class="picker" id="picker"></select>
                  <span class="hint board-notes"></span>
                </div>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="stage">
              <div class="boards" tabindex="-1"></div>
            </div>
            <textarea class="keys" autocapitalize="characters" autocomplete="off" spellcheck="false"></textarea>
          </div>

          <div class="card editor">
            <div class="segmented modes">
              <button data-mode="visual"><ha-icon icon="mdi:grid"></ha-icon>Visual</button>
              <button data-mode="text"><ha-icon icon="mdi:text"></ha-icon>Text</button>
            </div>
            <div class="visual-tools">
              <div class="row">
                <div class="segmented tools"></div>
                <div class="palette"></div>
                <div class="spacer"></div>
                <button class="icon undo" title="Undo (Ctrl+Z)"><ha-icon icon="mdi:undo"></ha-icon></button>
                <button class="icon redo" title="Redo (Ctrl+Shift+Z)"><ha-icon icon="mdi:redo"></ha-icon></button>
                <button class="clear"><ha-icon icon="mdi:delete-outline"></ha-icon>Clear</button>
                <button class="load"><ha-icon icon="mdi:download"></ha-icon>Load current</button>
              </div>
              <div class="hint tool-hint" style="margin-top: 8px"></div>
            </div>

            <div class="text-tools hidden">
              <div class="row" style="margin-bottom: 8px">
                <div class="palette text-palette"></div>
                <span class="hint">Click a color or symbol to insert it at the cursor.</span>
              </div>
              <textarea class="message" placeholder="Type a message and it's laid out across the board"></textarea>
              <div class="row" style="margin-top: 8px">
                <div class="field">Justify<div class="segmented justify"></div></div>
                <div class="field">Align<div class="segmented align"></div></div>
                <div class="spacer"></div>
                <span class="hint">Switch to Visual to fine-tune the layout.</span>
              </div>
            </div>
          </div>

          <div class="card">
            <div class="row">
              <label class="field">Transition<select class="strategy"></select></label>
              <label class="field">Show for (seconds)
                <input class="duration" type="number" min="10" max="43200" placeholder="Until replaced">
              </label>
              <label class="check"><input class="bypass" type="checkbox">Bypass quiet hours</label>
              <div class="spacer"></div>
              <span class="status"></span>
              <button class="primary send"><ha-icon icon="mdi:send"></ha-icon>Send</button>
            </div>
          </div>
        </div>
      </main>
    `;

    this._menuButton = document.createElement("ha-menu-button");
    this._menuButton.hass = this._hass;
    this._menuButton.narrow = this._narrow;
    root.querySelector(".menu").appendChild(this._menuButton);

    this._empty = root.querySelector(".empty");
    this._composer = root.querySelector(".composer");
    this._picker = root.querySelector(".picker");
    this._boardNotes = root.querySelector(".board-notes");
    this._stage = root.querySelector(".stage");
    this._boardsEl = root.querySelector(".boards");
    this._keys = root.querySelector(".keys");
    this._palette = root.querySelector(".visual-tools .palette");
    this._textPalette = root.querySelector(".text-palette");
    this._toolHint = root.querySelector(".tool-hint");
    this._messageInput = root.querySelector(".message");
    this._justifyButtons = root.querySelector(".justify");
    this._alignButtons = root.querySelector(".align");
    this._strategySelect = root.querySelector(".strategy");
    this._durationInput = root.querySelector(".duration");
    this._bypassInput = root.querySelector(".bypass");
    this._status = root.querySelector(".status");
    this._sendButton = root.querySelector(".send");
    this._undoButton = root.querySelector(".undo");
    this._redoButton = root.querySelector(".redo");

    this._fillAlignment(this._justifyButtons, JUSTIFY, "_justify");
    this._fillAlignment(this._alignButtons, ALIGN, "_align");
    this._fillSelect(this._strategySelect, TRANSITIONS);

    const tools = root.querySelector(".tools");
    for (const tool of TOOLS) {
      const button = document.createElement("button");
      button.dataset.tool = tool.id;
      button.title = tool.label;
      button.innerHTML = `<ha-icon icon="${tool.icon}"></ha-icon>`;
      button.append(tool.label);
      button.addEventListener("click", () => this._setTool(tool.id));
      tools.appendChild(button);
    }

    root.querySelectorAll(".modes button").forEach((button) =>
      button.addEventListener("click", () => this._setMode(button.dataset.mode))
    );
    this._picker.addEventListener("change", () => this._selectBoard(this._picker.value));
    this._undoButton.addEventListener("click", () => this._undo());
    this._redoButton.addEventListener("click", () => this._redo());
    root.querySelector(".clear").addEventListener("click", () => this._clear());
    root.querySelector(".load").addEventListener("click", () => this._loadCurrent());
    this._sendButton.addEventListener("click", () => this._send());
    this._bypassInput.addEventListener("change", () => this._updateBoardNotes());

    this._messageInput.addEventListener("input", () => {
      this._text = this._messageInput.value;
      this._scheduleLayout();
    });

    this._boardsEl.addEventListener("pointerdown", (ev) => this._onPointerDown(ev));
    this._boardsEl.addEventListener("pointermove", (ev) => this._onPointerMove(ev));
    this._boardsEl.addEventListener("pointerup", () => this._onPointerUp());
    this._boardsEl.addEventListener("pointercancel", () => this._onPointerUp());
    this._keys.addEventListener("keydown", (ev) => this._onKeyDown(ev));
    this._keys.addEventListener("beforeinput", (ev) => this._onBeforeInput(ev));
    this._keys.addEventListener("input", () => this._onInput());
    this._keys.addEventListener("blur", () => this._renderCursor());

    if (this._resizeObserver) this._resizeObserver.observe(this._stage);
    this._setTool(this._tool);
    this._setMode(this._mode);
  }

  _fillSelect(select, options) {
    select.replaceChildren(
      ...options.map(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        return option;
      })
    );
  }

  _fillAlignment(container, options, property) {
    container.replaceChildren(
      ...options.map(([value, label, icon]) => {
        const button = document.createElement("button");
        button.className = "icon";
        button.dataset.value = value;
        button.title = label;
        button.setAttribute("aria-label", label);
        button.innerHTML = `<ha-icon icon="${icon}"></ha-icon>`;
        button.addEventListener("click", () => {
          this[property] = value;
          this._renderAlignment();
          this._scheduleLayout();
        });
        return button;
      })
    );
    this._renderAlignment();
  }

  _renderAlignment() {
    for (const [container, value] of [
      [this._justifyButtons, this._justify],
      [this._alignButtons, this._align],
    ]) {
      container?.querySelectorAll("button").forEach((button) => {
        const selected = button.dataset.value === value;
        button.classList.toggle("selected", selected);
        button.setAttribute("aria-pressed", String(selected));
      });
    }
  }

  _renderBoardPicker() {
    this._fillSelect(
      this._picker,
      this._boards.map((board) => [board.device_id, board.name])
    );
  }

  _showEmpty(empty) {
    this._empty.classList.toggle("hidden", !empty);
    this._composer.classList.toggle("hidden", empty);
  }

  _updateBoardNotes() {
    const board = this._board;
    if (!board) return;
    const tiles = board.colors.length * board.colors[0].length;
    const kind =
      board.type === "array"
        ? `Note array, ${board.colors.length} × ${board.colors[0].length} (${tiles} Notes)`
        : `${board.type === "virtual" ? "Virtual " : ""}${board.model === "flagship" ? "Flagship" : "Note"}`;
    this._boardNotes.textContent = `${kind} · ${board.rows} × ${board.columns} bits`;

    if (board.quiet_hours && !this._bypassInput.checked) {
      this._setStatus(
        "Quiet hours are on, so this message will be skipped unless you bypass them.",
        "warning"
      );
    } else if (this._status.classList.contains("warning")) {
      this._setStatus("");
    }
  }

  _renderPalette() {
    if (!this._board) return;
    this._palette.replaceChildren(...this._swatches((code) => this._onPalette(code)));
    this._textPalette.replaceChildren(
      ...this._swatches((code) => this._insertIntoMessage(code)).map((swatch) => {
        // Keep the message box focused, so its cursor stays where it was
        swatch.addEventListener("mousedown", (ev) => ev.preventDefault());
        return swatch;
      })
    );
    this._renderPaletteSelection();
  }

  _swatches(onClick) {
    const theme = this._themeAt(0, 0);
    return PALETTE.map((code) => {
      const swatch = document.createElement("div");
      swatch.className = "swatch";
      swatch.dataset.code = code;
      swatch.style.background = theme.bit;
      if (code === HEART_CODE) {
        const heart = this._board.heart;
        swatch.appendChild(heart ? this._heartElement() : document.createTextNode("°"));
        swatch.style.color = theme.text;
        swatch.title = heart ? "Heart" : "Degree sign";
      } else {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.style.background = theme.colors[code];
        swatch.appendChild(chip);
        swatch.title = COLOR_NAMES[theme.colors[code].toUpperCase()] || `Color ${code}`;
      }
      swatch.addEventListener("click", () => onClick(code));
      return swatch;
    });
  }

  _renderPaletteSelection() {
    this._palette.querySelectorAll(".swatch").forEach((swatch) => {
      swatch.classList.toggle(
        "selected",
        this._tool !== "type" && this._tool !== "eraser" && Number(swatch.dataset.code) === this._code
      );
    });
  }

  _buildBoard() {
    const board = this._board;
    const tileRows = board.colors.length;
    const tileColumns = board.colors[0].length;
    this._boardsEl.style.gridTemplateColumns = `repeat(${tileColumns}, auto)`;
    const edge = (outer, gap) => (outer ? "var(--margin)" : `calc(var(${gap}) / 2)`);
    this._cells = blankGrid(board.rows, board.columns);

    const tiles = [];
    for (let tileRow = 0; tileRow < tileRows; tileRow++) {
      for (let tileColumn = 0; tileColumn < tileColumns; tileColumn++) {
        const theme = this._themes[board.colors[tileRow][tileColumn]];
        const tile = document.createElement("div");
        tile.className = board.show_frame ? "board framed" : "board";
        tile.style.background = theme.frame;
        tile.style.setProperty("--outline-color", theme.bit);
        tile.style.gridTemplateColumns = `repeat(${board.board_columns}, var(--bit))`;
        tile.style.setProperty("--stripe-color", theme.frame);
        if (!board.show_frame) {
          tile.style.padding = [
            edge(tileRow === 0, "--gap-y"),
            edge(tileColumn === tileColumns - 1, "--gap-x"),
            edge(tileRow === tileRows - 1, "--gap-y"),
            edge(tileColumn === 0, "--gap-x"),
          ].join(" ");
        }
        for (let r = 0; r < board.board_rows; r++) {
          for (let c = 0; c < board.board_columns; c++) {
            const row = tileRow * board.board_rows + r;
            const column = tileColumn * board.board_columns + c;
            const cell = document.createElement("div");
            cell.className = "bit";
            cell.dataset.row = row;
            cell.dataset.column = column;
            cell.style.background = theme.bit;
            cell.style.color = theme.text;
            this._cells[row][column] = cell;
            tile.appendChild(cell);
          }
        }
        if (board.show_frame) {
          const logo = document.createElement("div");
          logo.className = "logo";
          logo.style.color = theme.logo;
          logo.textContent = LOGO_TEXT;
          tile.appendChild(logo);
        }
        tiles.push(tile);
      }
    }
    this._boardsEl.replaceChildren(...tiles);
    this._sizeBoard();
    this._renderGrid();
  }

  _sizeBoard() {
    const board = this._board;
    if (!board || !this._stage) return;
    const tileColumns = board.colors[0].length;
    const width = this._stage.clientWidth;
    if (!width) return;
    const bit = this._bitSize;
    const frame = board.frame;
    // Framed Notes in an array are 1% of a Note's height apart, as in the
    // board image. Without a frame, the margin matches the bit spacing.
    const boardGap = board.show_frame ? frame.height / 100 : 0;
    const inches = board.show_frame
      ? tileColumns * frame.width + (tileColumns - 1) * boardGap
      : board.columns * bit.width + (board.columns + 1) * bit.gap_x;
    const pxPerInch = Math.max(
      MIN_BIT_WIDTH / bit.width,
      Math.min(MAX_BIT_WIDTH / bit.width, (width - 2) / inches)
    );
    const px = (value) => `${value * pxPerInch}px`;
    const style = this._boardsEl.style;
    style.setProperty("--bit", px(bit.width));
    style.setProperty("--bit-h", px(bit.height));
    style.setProperty("--gap-x", px(bit.gap_x));
    style.setProperty("--gap-y", px(bit.gap_y));
    style.setProperty("--margin", px(bit.gap_x));
    style.setProperty("--board-gap", px(boardGap));
    style.setProperty("--board-w", px(frame.width));
    style.setProperty("--board-h", px(frame.height));
    style.setProperty("--outline", px(frame.thickness));
    style.setProperty("--frame-border", px(frame.border));
    style.setProperty("--logo-size", px(frame.logo.size));
    // The logo's descender line, measured from the bottom inside the outline
    style.setProperty("--logo-bottom", px(frame.height - frame.thickness - frame.logo.descender));
  }

  _renderGrid() {
    for (let row = 0; row < this._grid.length; row++) {
      for (let column = 0; column < this._grid[row].length; column++) {
        this._renderCell(row, column);
      }
    }
    this._renderCursor();
  }

  _renderCell(row, column) {
    const cell = this._cells[row]?.[column];
    if (!cell) return;
    const code = this._grid[row][column];
    const theme = this._themeAt(row, column);
    cell.replaceChildren();
    cell.classList.toggle("color", COLOR_CODES.includes(code));
    if (code === HEART_CODE && this._board.heart) {
      const img = this._heartElement();
      img.className = "heart";
      cell.appendChild(img);
    } else if (COLOR_CODES.includes(code)) {
      const fill = document.createElement("div");
      fill.className = "fill";
      fill.style.background = theme.colors[code];
      cell.appendChild(fill);
    } else if (code !== BLANK_CODE) {
      cell.textContent = (this._symbols[code] || " ").trim();
    }
  }

  _heartElement() {
    const img = document.createElement("img");
    img.src = this._heartImage;
    img.alt = "❤️";
    img.draggable = false;
    return img;
  }

  _renderCursor() {
    this._boardsEl
      .querySelectorAll(".bit.cursor")
      .forEach((cell) => cell.classList.remove("cursor"));
    const typing =
      this._mode === "visual" &&
      this._tool === "type" &&
      this.shadowRoot.activeElement === this._keys;
    if (typing) {
      this._cells[this._cursor.row]?.[this._cursor.column]?.classList.add("cursor");
    }
  }

  _updateHistoryButtons() {
    this._undoButton.disabled = !this._history.length;
    this._redoButton.disabled = !this._future.length;
  }

  _setStatus(message, kind = "") {
    this._status.textContent = message;
    this._status.className = `status ${kind}`;
  }

  // ---- Modes and tools --------------------------------------------------

  _setMode(mode) {
    this._mode = mode;
    this.shadowRoot
      .querySelectorAll(".modes button")
      .forEach((b) => b.classList.toggle("selected", b.dataset.mode === mode));
    this.shadowRoot.querySelector(".visual-tools").classList.toggle("hidden", mode !== "visual");
    this.shadowRoot.querySelector(".text-tools").classList.toggle("hidden", mode !== "text");
    this._textPushed = false;
    if (mode === "text") {
      this._syncText();
      this._messageInput.focus();
    }
    this._renderCursor();
  }

  _setTool(tool) {
    this._tool = tool;
    this.shadowRoot
      .querySelectorAll(".tools button")
      .forEach((b) => b.classList.toggle("selected", b.dataset.tool === tool));
    TOOLS.forEach(({ id }) => this._boardsEl.classList.toggle(`tool-${id}`, id === tool));
    this._toolHint.textContent = {
      type: "Click a bit and type. Pick a color or the heart to insert it. Arrow keys move, Enter starts a new line.",
      pen: "Click or drag across bits to paint them with the selected color.",
      fill: "Click a bit to fill it and the matching bits around it with the selected color.",
      eraser: "Click or drag across bits to clear them.",
    }[tool];
    if (tool !== "type") this._keys.blur();
    this._renderPaletteSelection();
    this._renderCursor();
  }

  _onPalette(code) {
    if (this._tool === "type") {
      this._typeCodes([code]);
      this._keys.focus({ preventScroll: true });
      return;
    }
    if (this._tool === "eraser") this._setTool("pen");
    this._code = code;
    this._renderPaletteSelection();
  }

  // ---- Editing ----------------------------------------------------------

  _pushHistory(action) {
    if (action && action === this._lastAction) return;
    this._history.push(copyGrid(this._grid));
    if (this._history.length > 200) this._history.shift();
    this._future = [];
    this._lastAction = action;
    this._updateHistoryButtons();
  }

  _changed() {
    this._saveDraft();
    this._updateHistoryButtons();
  }

  _setCode(row, column, code) {
    if (this._grid[row]?.[column] === undefined || this._grid[row][column] === code) return;
    this._grid[row][column] = code;
    this._renderCell(row, column);
  }

  _setGrid(grid) {
    this._grid = copyGrid(grid);
    this._renderGrid();
    this._changed();
  }

  _undo() {
    if (!this._history.length) return;
    this._future.push(copyGrid(this._grid));
    this._lastAction = null;
    this._setGrid(this._history.pop());
  }

  _redo() {
    if (!this._future.length) return;
    this._history.push(copyGrid(this._grid));
    this._lastAction = null;
    this._setGrid(this._future.pop());
  }

  _clear() {
    this._pushHistory();
    this._setGrid(blankGrid(this._board.rows, this._board.columns));
  }

  async _loadCurrent() {
    await this._loadBoards(true);
    if (!this._board) return;
    this._pushHistory();
    this._setGrid(this._board.characters);
    this._setStatus("Loaded what the board is showing.", "success");
  }

  _fill(row, column, code) {
    const target = this._grid[row][column];
    if (target === code) return;
    const stack = [[row, column]];
    while (stack.length) {
      const [r, c] = stack.pop();
      if (this._grid[r]?.[c] !== target) continue;
      this._setCode(r, c, code);
      stack.push([r + 1, c], [r - 1, c], [r, c + 1], [r, c - 1]);
    }
  }

  _cellFromEvent(ev) {
    const element = this.shadowRoot.elementFromPoint(ev.clientX, ev.clientY);
    const cell = element?.closest?.(".bit");
    if (!cell) return null;
    return { row: Number(cell.dataset.row), column: Number(cell.dataset.column) };
  }

  _onPointerDown(ev) {
    if (!this._board || ev.button > 0) return;
    const cell = this._cellFromEvent(ev);
    if (!cell) return;
    ev.preventDefault();
    if (this._mode === "text") this._setMode("visual");

    if (this._tool === "type") {
      this._cursor = cell;
      this._lineStart = cell.column;
      this._lastAction = null;
      this._keys.focus({ preventScroll: true });
      this._renderCursor();
      return;
    }
    if (this._tool === "fill") {
      this._pushHistory();
      this._fill(cell.row, cell.column, this._code);
      this._changed();
      return;
    }
    this._pushHistory();
    this._painting = true;
    this._boardsEl.setPointerCapture?.(ev.pointerId);
    this._paint(cell);
  }

  _onPointerMove(ev) {
    if (!this._painting) return;
    const cell = this._cellFromEvent(ev);
    if (cell) this._paint(cell);
  }

  _onPointerUp() {
    if (!this._painting) return;
    this._painting = false;
    this._lastAction = null;
    this._changed();
  }

  _paint({ row, column }) {
    this._setCode(row, column, this._tool === "eraser" ? BLANK_CODE : this._code);
  }

  _codesFor(text) {
    const codes = [];
    for (const char of text) {
      // Skip the variation selector in ❤️
      if (char === "️") continue;
      const code = this._charCodes.get(char) ?? this._charCodes.get(char.toUpperCase());
      if (code !== undefined) codes.push(code);
    }
    return codes;
  }

  _typeCodes(codes) {
    if (!codes.length) return;
    this._pushHistory("type");
    const { rows, columns } = this._board;
    for (const code of codes) {
      this._setCode(this._cursor.row, this._cursor.column, code);
      if (this._cursor.column < columns - 1) {
        this._cursor.column += 1;
      } else if (this._cursor.row < rows - 1) {
        this._cursor = { row: this._cursor.row + 1, column: 0 };
      }
    }
    this._changed();
    this._renderCursor();
  }

  _backspace() {
    const { columns } = this._board;
    if (this._cursor.column > 0) {
      this._cursor.column -= 1;
    } else if (this._cursor.row > 0) {
      this._cursor = { row: this._cursor.row - 1, column: columns - 1 };
    } else {
      return;
    }
    this._pushHistory("type");
    this._setCode(this._cursor.row, this._cursor.column, BLANK_CODE);
    this._changed();
    this._renderCursor();
  }

  _moveCursor(rowDelta, columnDelta) {
    const { rows, columns } = this._board;
    this._cursor = {
      row: Math.min(rows - 1, Math.max(0, this._cursor.row + rowDelta)),
      column: Math.min(columns - 1, Math.max(0, this._cursor.column + columnDelta)),
    };
    this._lastAction = null;
    this._renderCursor();
  }

  _onKeyDown(ev) {
    if (!this._board || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const handlers = {
      ArrowLeft: () => this._moveCursor(0, -1),
      ArrowRight: () => this._moveCursor(0, 1),
      ArrowUp: () => this._moveCursor(-1, 0),
      ArrowDown: () => this._moveCursor(1, 0),
      Home: () => this._moveCursor(0, -this._cursor.column),
      End: () => this._moveCursor(0, this._board.columns),
      Backspace: () => this._backspace(),
      Delete: () => {
        this._pushHistory("type");
        this._setCode(this._cursor.row, this._cursor.column, BLANK_CODE);
        this._changed();
      },
      Enter: () => {
        if (this._cursor.row < this._board.rows - 1) {
          this._cursor = { row: this._cursor.row + 1, column: this._lineStart };
          this._lastAction = null;
          this._renderCursor();
        }
      },
      Escape: () => this._keys.blur(),
    };
    const handler = handlers[ev.key];
    if (handler) {
      ev.preventDefault();
      handler();
    }
  }

  _onBeforeInput(ev) {
    // Phone keyboards send deletions as input events rather than key presses
    if (ev.inputType?.startsWith("delete")) {
      ev.preventDefault();
      this._backspace();
    }
  }

  _onInput() {
    const text = this._keys.value;
    this._keys.value = "";
    this._typeCodes(this._codesFor(text));
  }

  _onShortcut(ev) {
    if (!(ev.ctrlKey || ev.metaKey) || this._mode !== "visual" || !this._board) return;
    // Leave undo in other text fields, such as Home Assistant dialogs, alone
    const target = ev.composedPath()[0];
    const editable =
      target instanceof HTMLElement &&
      (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
    if (editable && target !== this._keys) return;
    const key = ev.key.toLowerCase();
    if (key === "z" && !ev.shiftKey) {
      ev.preventDefault();
      this._undo();
    } else if ((key === "z" && ev.shiftKey) || key === "y") {
      ev.preventDefault();
      this._redo();
    }
  }

  // ---- Text mode --------------------------------------------------------

  _syncText() {
    // Keep the message and the board in step when Text mode opens
    if (this._textGrid && sameGrid(this._grid, this._textGrid)) return;
    if (isBlank(this._grid)) {
      // Show the message on the board
      if (this._text.trim()) this._layout();
      return;
    }
    // The board shows something else, so start the message from it
    this._text = this._gridText(this._grid);
    this._messageInput.value = this._text;
    this._messageInput.setSelectionRange(this._text.length, this._text.length);
    this._saveDraft();
  }

  _gridText(grid) {
    const lines = grid.map((row) =>
      row
        .map((code) => {
          if (code === HEART_CODE) return this._board.heart ? "❤️" : "°";
          if (code in TEXT_TOKENS) return TEXT_TOKENS[code];
          if (COLOR_CODES.includes(code)) return `{${code}}`;
          return this._symbols[code] || " ";
        })
        .join("")
        .trim()
    );
    // Drop blank lines above and below the message; alignment places it
    while (lines.length && !lines[0]) lines.shift();
    while (lines.length && !lines[lines.length - 1]) lines.pop();
    return lines.join("\n");
  }

  _insertIntoMessage(code) {
    const token =
      code === HEART_CODE ? (this._board.heart ? "❤️" : "°") : TEXT_TOKENS[code];
    const input = this._messageInput;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    input.setRangeText(token, start, end, "end");
    input.focus();
    this._text = input.value;
    this._scheduleLayout();
  }

  _scheduleLayout() {
    this._saveDraft();
    clearTimeout(this._layoutTimer);
    this._layoutTimer = setTimeout(() => this._layout(), LAYOUT_DELAY_MS);
  }

  async _layout() {
    if (!this._board) return;
    const request = ++this._layoutRequest;
    const deviceId = this._board.device_id;
    let result;
    try {
      result = await this._hass.callWS({
        type: "vestaboard/layout",
        device_id: deviceId,
        message: this._text,
        justify: this._justify,
        align: this._align,
      });
    } catch (err) {
      if (request === this._layoutRequest) {
        this._setStatus(`Couldn't lay out the message: ${err.message || err}`, "error");
      }
      return;
    }
    // Ignore a stale layout, or one for a board that's no longer selected
    if (request !== this._layoutRequest || this._board?.device_id !== deviceId) return;
    if (!this._textPushed) {
      this._pushHistory();
      this._textPushed = true;
    }
    this._lastAction = null;
    this._setGrid(result.characters);
    this._textGrid = copyGrid(result.characters);
    if (this._status.classList.contains("error")) this._setStatus("");
  }

  // ---- Sending ----------------------------------------------------------

  async _send() {
    if (!this._board) return;
    // Another board may be selected while this one is being sent to
    const { device_id: deviceId, name } = this._board;
    const data = {
      device_id: deviceId,
      vbml: { components: [{ rawCharacters: this._grid }] },
    };
    if (this._strategySelect.value) data.strategy = this._strategySelect.value;
    const duration = Number(this._durationInput.value);
    if (this._durationInput.value) {
      if (!Number.isInteger(duration) || duration < 10 || duration > 43200) {
        this._setStatus("Show for must be a whole number of seconds from 10 to 43200.", "error");
        return;
      }
      data.duration = duration;
    }
    if (this._bypassInput.checked) data.bypass_quiet_hours = true;

    this._sendButton.disabled = true;
    this._setStatus("Submitting…");
    try {
      await this._hass.callService("vestaboard", "message", data);
      // The action doesn't report whether quiet hours skipped the message
      this._setStatus(
        data.bypass_quiet_hours
          ? `Submitted to ${name}.`
          : `Submitted to ${name}. Quiet hours may skip it.`,
        "success"
      );
    } catch (err) {
      this._setStatus(`Couldn't send: ${err.message || err}`, "error");
    } finally {
      this._sendButton.disabled = false;
    }
    await this._loadBoards(true);
  }
}

if (!customElements.get("vestaboard-composer-panel")) {
  customElements.define("vestaboard-composer-panel", VestaboardComposerPanel);
}
