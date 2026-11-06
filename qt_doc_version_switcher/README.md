# qt_doc_version_switcher

Userscript for doc.qt.io. It redirects each doc page to your preferred Qt version (6.8 by default). It also adds a floating switcher: Qt 5.9, Qt 5.15, Qt 6.8 and Qt 6 (latest). The script remembers the last version you click.

## Install

1. Install a userscript manager in your browser:
   - [Tampermonkey](https://www.tampermonkey.net/) (Chrome, Firefox, Edge)
   - [Violentmonkey](https://violentmonkey.github.io/) (Firefox)
2. Open the raw URL below. The manager shows an install page.
3. Click **Install**.

```
https://raw.githubusercontent.com/TEA-ebook/ereader-tooling/main/qt_doc_version_switcher/qt_doc_version_switcher.user.js
```

### Tampermonkey on Chrome / Edge

Chrome blocks userscripts by default. Enable them one time:

1. Open `chrome://extensions` (or `edge://extensions`).
2. Open the **Details** page of Tampermonkey.
3. Enable **Allow User Scripts**. On older browser versions, enable **Developer mode** at the top right.

If you do not do this, the script installs but does not run.

### Violentmonkey

No extra step. Open the raw URL, then click **Confirm installation**.

## Updates

The script updates automatically from the `main` branch. To get an update now:

- Tampermonkey: click the extension icon, then click **Check for userscript updates**.
- Violentmonkey: open the dashboard, then click the **Check for updates** button (refresh icon).

Install from the raw URL only. If you copy and paste the script, automatic updates can stop.

For maintainers: increase `@version` in the script header each time you push a change. Without that, users do not get the update.
