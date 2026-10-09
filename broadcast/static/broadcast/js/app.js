/* ==========================================================================
   Teacher2Discord — Application JavaScript
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    initAlertDismiss();
    initDeleteModal();
    initFormLoaders();
});


/* --------------------------------------------------------------------------
   Auto-dismiss alert messages after 5 seconds
   -------------------------------------------------------------------------- */
function initAlertDismiss() {
    const container = document.getElementById('message-container');
    if (!container) return;

    // Delegate click events for close buttons
    container.addEventListener('click', (e) => {
        if (e.target.matches('.close-btn')) {
            e.target.parentElement.remove();
        }
    });

    setTimeout(() => {
        container.style.transition = 'opacity 0.5s ease';
        container.style.opacity = '0';
        setTimeout(() => container.remove(), 500);
    }, 5000);
}


/* --------------------------------------------------------------------------
   Delete confirmation modal
   -------------------------------------------------------------------------- */
let pendingDeleteForm = null;

function initDeleteModal() {
    const modal = document.getElementById('deleteModal');
    const confirmBtn = document.getElementById('deleteModalConfirm');
    if (!modal || !confirmBtn) return;

    confirmBtn.addEventListener('click', () => {
        if (pendingDeleteForm) {
            pendingDeleteForm.submit();
        }
        closeDeleteModal();
    });

    // Delegate click events for delete triggers
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-action="confirm-delete"]');
        if (btn) {
            confirmDelete(btn, btn.dataset.title, btn.dataset.desc);
        }
        
        const cancelBtn = e.target.closest('[data-dismiss="modal"]');
        if (cancelBtn) {
            closeDeleteModal();
        }
        
        const copyBtn = e.target.closest('[data-action="copy-link"]');
        if (copyBtn) {
            const target = document.getElementById(copyBtn.dataset.target);
            if (target) {
                navigator.clipboard.writeText(target.innerText);
                copyBtn.innerText = 'Copied!';
                setTimeout(() => copyBtn.innerText = 'Copy', 2000);
            }
        }
        
        const loadBtn = e.target.closest('[data-action="load-more"]');
        if (loadBtn) {
            loadMoreMessages(loadBtn);
        }
    });

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeDeleteModal();
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeDeleteModal();
    });
}

function confirmDelete(btn, title, desc) {
    pendingDeleteForm = btn.closest('form');
    document.getElementById('deleteModalTitle').textContent = title || 'Delete this item?';
    document.getElementById('deleteModalDesc').textContent = desc || 'This action cannot be undone.';
    document.getElementById('deleteModal').classList.add('active');
}

function closeDeleteModal() {
    document.getElementById('deleteModal').classList.remove('active');
    pendingDeleteForm = null;
}


/* --------------------------------------------------------------------------
   Loading spinners on form submit buttons
   -------------------------------------------------------------------------- */
function initFormLoaders() {
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', function () {
            const btn = form.querySelector('button[type="submit"]:not([data-no-loader])');
            if (btn && !btn.disabled) {
                btn.disabled = true;
                const originalHTML = btn.innerHTML;
                btn.innerHTML = '<span class="spinner"></span> ' + btn.textContent.trim();
                // Re-enable after timeout in case of error
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerHTML = originalHTML;
                }, 8000);
            }
        });
    });
}


/* --------------------------------------------------------------------------
   Load more messages (AJAX pagination)
   -------------------------------------------------------------------------- */
function loadMoreMessages(btn) {
    const container = document.getElementById('messageList');
    const url = btn.dataset.url;
    const nextPage = parseInt(btn.dataset.nextPage);
    const totalPages = parseInt(btn.dataset.totalPages);

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Loading…';

    fetch(`${url}?page=${nextPage}`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
        .then(response => {
            if (!response.ok) throw new Error('Network error');
            return response.text();
        })
        .then(html => {
            if (html.trim()) {
                container.insertAdjacentHTML('beforeend', html);
            }

            if (nextPage >= totalPages) {
                // No more pages — remove the button
                btn.parentElement.remove();
            } else {
                btn.dataset.nextPage = nextPage + 1;
                btn.disabled = false;
                btn.innerHTML = 'Load Older Messages';
            }
        })
        .catch(() => {
            btn.disabled = false;
            btn.innerHTML = 'Load Older Messages';
        });
}
