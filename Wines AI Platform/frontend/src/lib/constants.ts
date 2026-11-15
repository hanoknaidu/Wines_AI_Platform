/** Mirrors of backend `config.py` values the UI has to respect.
 *
 * No wine vocabulary lives here, or anywhere else in src/ outside src/mocks/ — every
 * label, level, hedge and chip arrives from GET /meta/taste-axes or a `chips` frame.
 */

export const API_BASE = "/api/v1";

/** `max_message_chars`. The counter appears at COUNTER_FROM, not before. */
export const MAX_MESSAGE_CHARS = 2000;
export const COUNTER_FROM = 1800;

/** `conversation_page_size` and `title_max_chars`. */
export const PAGE_SIZE = 20;
export const TITLE_MAX_CHARS = 52;

/** `rate_limit_turns_per_min`, for the 429 copy. */
export const TURNS_PER_MIN = 30;

export const SIDEBAR_STORAGE_KEY = "wa.sidebar.collapsed";
export const PANEL_STORAGE_KEY = "wa.panel.open";

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== "false";
export const SHOW_DIAGNOSTICS = import.meta.env.VITE_SHOW_DIAGNOSTICS !== "false";
