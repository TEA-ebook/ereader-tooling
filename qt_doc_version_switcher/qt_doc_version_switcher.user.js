// ==UserScript==
// @name         Qt Doc Version Switcher
// @namespace    https://doc.qt.io/
// @version      1.1.0
// @description  Always redirect Qt docs to Qt 6.8 by default, with a floating version switcher (5.9 / 5.15 / 6.8 / latest 6)
// @author       Adrien ALBOUY
// @match        https://doc.qt.io/*
// @updateURL    https://raw.githubusercontent.com/TEA-ebook/ereader-tooling/main/qt_doc_version_switcher/qt_doc_version_switcher.user.js
// @downloadURL  https://raw.githubusercontent.com/TEA-ebook/ereader-tooling/main/qt_doc_version_switcher/qt_doc_version_switcher.user.js
// @grant        GM_setValue
// @grant        GM_getValue
// @run-at       document-start
// ==/UserScript==

(function () {
  'use strict';

  // ─── URL structure reference ──────────────────────────────────────────────
  //
  //  Qt 5.9  →  https://doc.qt.io/archives/qt-5.9/qstring.html
  //  Qt 5.15 →  https://doc.qt.io/archives/qt-5.15/qstring.html
  //  Qt 6.8  →  https://doc.qt.io/qt-6.8/qstring.html
  //  Qt 6    →  https://doc.qt.io/qt-6/qstring.html   (always the latest Qt 6 release)
  //
  // ─────────────────────────────────────────────────────────────────────────

  const VERSIONS = {
    '5.9':  { prefix: 'archives', slug: 'qt-5.9',  label: 'Qt 5.9'  },
    '5.15': { prefix: 'archives', slug: 'qt-5.15', label: 'Qt 5.15' },
    '6.8':  { prefix: null,       slug: 'qt-6.8',  label: 'Qt 6.8'  },
    '6':    { prefix: null,       slug: 'qt-6',    label: 'Qt 6 (latest)' },
  };

  // Display order of the switcher buttons. Needed because JS objects list
  // integer-like keys ('6') before all other keys, whatever the insertion order.
  const VERSION_ORDER = ['5.9', '5.15', '6.8', '6'];

  // Every slug we recognise, mapped to a canonical version key.
  // Covers minor variants (qt-6.2, qt-6.8 …) so old bookmarks still match.
  const SLUG_TO_VERSION = {
    'qt-5':        '5.9',   // legacy alias occasionally seen
    'qt-5.9':      '5.9',
    'qt-5.15':     '5.15',
    'qt-5.15-lts': '5.15',
    'qt-6':        '6',
    'qt-6.0':      '6.8', 'qt-6.1': '6.8', 'qt-6.2': '6.8', 'qt-6.3': '6.8',
    'qt-6.4':      '6.8', 'qt-6.5': '6.8', 'qt-6.6': '6.8', 'qt-6.7': '6.8',
    'qt-6.8':      '6.8', 'qt-6.x': '6.8',
    'qt-6.9':      '6',   'qt-6.10': '6', 'qt-6.11': '6', 'qt-6.12': '6',
  };

  const DEFAULT_VERSION = '6.8';
  const STORAGE_KEY = 'qt_doc_preferred_version';

  function getPreferred() {
    const stored = GM_getValue(STORAGE_KEY, DEFAULT_VERSION);
    // Guards against stale values from a VERSIONS key that no longer exists.
    // An unknown key would otherwise throw in buildPath() and kill the script
    // silently.
    if (Object.prototype.hasOwnProperty.call(VERSIONS, stored)) return stored;
    return DEFAULT_VERSION;
  }
  function setPreferred(v) { GM_setValue(STORAGE_KEY, v); }

  /**
   * Parse a doc.qt.io pathname into { version, tail } or null if unrecognised.
   *
   * Handles:
   *   /qt-6/qstring.html                  → { version:'6',   tail:'qstring.html' }
   *   /archives/qt-5.9/qstring.html       → { version:'5.9', tail:'qstring.html' }
   *   /archives/qt-5.15/qtwidgets/...     → { version:'5.15', tail:'qtwidgets/...' }
   */
  function parsePath(pathname) {
    const segs = pathname.split('/').filter(Boolean);
    if (segs.length === 0) return null;

    let slug, tail;

    if (segs[0] === 'archives') {
      slug = segs[1];
      tail = segs.slice(2).join('/');
    } else {
      slug = segs[0];
      tail = segs.slice(1).join('/');
    }

    const version = SLUG_TO_VERSION[slug];
    if (!version) return null;

    return { version, tail };
  }

  /**
   * Build a doc.qt.io pathname for a given version key and page tail.
   *   buildPath('5.9',  'qstring.html') → '/archives/qt-5.9/qstring.html'
   *   buildPath('6',    'qstring.html') → '/qt-6/qstring.html'
   */
  function buildPath(versionKey, tail) {
    const { prefix, slug } = VERSIONS[versionKey];
    const parts = prefix ? [prefix, slug] : [slug];
    if (tail) parts.push(tail);
    return '/' + parts.join('/');
  }

  // ─── Redirect logic (runs at document-start on doc.qt.io) ────────────────

  const host = location.hostname;

  if (host === 'doc.qt.io') {
      const parsed = parsePath(location.pathname);

      if (parsed) {
        const preferred = getPreferred();
        const canonicalPath = buildPath(preferred, parsed.tail);

        if (canonicalPath !== location.pathname) {
          const newUrl = 'https://doc.qt.io'
            + canonicalPath
            + location.search + location.hash;
          location.replace(newUrl);
          return; // navigating away, stop all further execution
        }
      }
    }

  // ─── Search engine: rewrite doc.qt.io result links ───────────────────────

    function patchSearchLinks() {
        const preferred = getPreferred();

        document.querySelectorAll('a[href*="doc.qt.io"]').forEach(a => {
            try {
                const url = new URL(a.href);
                if (url.hostname !== 'doc.qt.io') return;

                const parsed = parsePath(url.pathname);
                if (!parsed) return;

                const canonicalPath = buildPath(preferred, parsed.tail);
                if (url.pathname === canonicalPath) return; // already correct

                url.pathname = canonicalPath;
                a.href = url.toString();
            } catch (_) {}
        });
    }


  // ─── Floating version-switcher widget (doc.qt.io only) ───────────────────

  if (host !== 'doc.qt.io') return;

  document.addEventListener('DOMContentLoaded', injectWidget);

  function injectWidget() {
    // Highlight the version that the current page *actually* is, not just the
    // stored preference — handles direct links / bookmarks to other versions.
    const parsed = parsePath(location.pathname);
    const activeVersion = (parsed && parsed.version) ? parsed.version : getPreferred();

    const style = document.createElement('style');
    style.textContent = `
      #qt-version-switcher {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 999999;
        font-family: 'Segoe UI', system-ui, sans-serif;
        font-size: 13px;
      }
      #qtvs-inner {
        display: flex;
        align-items: center;
        gap: 8px;
        background: #1a1a2e;
        border: 1px solid #41cd52;
        border-radius: 10px;
        padding: 8px 14px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.45), 0 0 0 1px rgba(65,205,82,0.15);
        color: #e0e0e0;
        cursor: default;
        transition: box-shadow 0.2s;
      }
      #qtvs-inner:hover {
        box-shadow: 0 6px 32px rgba(65,205,82,0.25), 0 0 0 1px rgba(65,205,82,0.35);
      }
      #qtvs-icon { font-size: 15px; line-height: 1; opacity: 0.75; }
      #qtvs-label {
        font-weight: 600;
        letter-spacing: 0.04em;
        color: #41cd52;
        margin-right: 4px;
        white-space: nowrap;
      }
      #qtvs-options { display: flex; gap: 5px; }
      .qtvs-btn {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 6px;
        color: #c0c0c0;
        padding: 4px 10px;
        cursor: pointer;
        font-size: 12px;
        font-family: inherit;
        font-weight: 500;
        transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.1s;
        white-space: nowrap;
      }
      .qtvs-btn:hover {
        background: rgba(65,205,82,0.15);
        border-color: #41cd52;
        color: #fff;
        transform: translateY(-1px);
      }
      .qtvs-btn.qtvs-active {
        background: #41cd52;
        border-color: #41cd52;
        color: #0d1117;
        font-weight: 700;
        cursor: default;
      }
      .qtvs-btn.qtvs-active:hover { transform: none; }
    `;

    const widget = document.createElement('div');
    widget.id = 'qt-version-switcher';
    widget.innerHTML = `
      <div id="qtvs-inner">
        <div id="qtvs-options">
          ${VERSION_ORDER.map(v => `
            <button class="qtvs-btn${v === activeVersion ? ' qtvs-active' : ''}" data-version="${v}">
              ${VERSIONS[v].label}
            </button>
          `).join('')}
        </div>
      </div>
    `;

    document.head.appendChild(style);
    document.body.appendChild(widget);

    widget.querySelectorAll('.qtvs-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const v = btn.dataset.version;
        if (v === getPreferred()) return;

        setPreferred(v);

        const parsed = parsePath(location.pathname);
        const tail = parsed ? parsed.tail : '';
        const newUrl = 'https://doc.qt.io'
          + buildPath(v, tail)
          + location.search + location.hash;
        location.assign(newUrl);
      });
    });
  }

})();