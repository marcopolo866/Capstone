        // Shared UI utilities loaded before all other app modules.
        // Keep this file dependency-light because the rest of the split
        // browser runtime assumes these globals already exist.

        // ---------------------------------------------------------------------------
        // Error banner
        // Shows a persistent, dismissible error banner inside #status-message.
        // Falls back to console.error if the element doesn't exist.
        // ---------------------------------------------------------------------------

        function showErrorBanner(message, err) {
            const container = document.getElementById('status-message');
            if (!container) {
                console.error('[Error]', message, err || '');
                return;
            }
            // Remove any existing banner so we don't stack duplicates.
            const existing = container.querySelector('.error-banner');
            if (existing) existing.remove();

            const banner = document.createElement('div');
            banner.className = 'error-banner';

            const text = document.createElement('span');
            text.textContent = message;
            banner.appendChild(text);

            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.textContent = '×';
            closeBtn.setAttribute('aria-label', 'Dismiss error');
            closeBtn.addEventListener('click', () => banner.remove());
            banner.appendChild(closeBtn);

            container.insertBefore(banner, container.firstChild);
            console.error('[Error]', message, err || '');
        }

        function hideErrorBanner() {
            const container = document.getElementById('status-message');
            if (!container) return;
            const existing = container.querySelector('.error-banner');
            if (existing) existing.remove();
        }

        // Note: reportDebugError and showStatus are defined in 07-visualization-api-bootstrap.js
        // which loads after this file. At event-handler call time all scripts are loaded, so
        // those functions are available. Do NOT redefine them here.
