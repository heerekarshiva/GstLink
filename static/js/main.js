// GSTLink — Main JavaScript

// GST Live Calculator
function setupGSTCalculator() {
  const amountInput = document.getElementById('amount');
  const gstRateSelect = document.getElementById('gst_rate');
  const supplierStateEl = document.getElementById('supplier_state_hidden');
  const clientIdSelect = document.getElementById('client_id');

  if (!amountInput || !gstRateSelect) return;

  async function recalculate() {
    const amount = parseFloat(amountInput.value) || 0;
    const gstRate = parseFloat(gstRateSelect.value) || 18;
    const supplierState = supplierStateEl ? supplierStateEl.value : '';
    
    // Get client state from selected option
    let clientState = '';
    if (clientIdSelect && clientIdSelect.selectedOptions[0]) {
      clientState = clientIdSelect.selectedOptions[0].dataset.state || '';
    }

    if (amount <= 0) { resetGSTDisplay(); return; }

    try {
      const res = await fetch('/api/calculate-gst', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({amount, gst_rate: gstRate, supplier_state: supplierState, client_state: clientState})
      });
      const data = await res.json();
      updateGSTDisplay(data);
    } catch(e) { console.error(e); }
  }

  amountInput.addEventListener('input', recalculate);
  gstRateSelect.addEventListener('change', recalculate);
  if (clientIdSelect) clientIdSelect.addEventListener('change', recalculate);
}

function updateGSTDisplay(data) {
  const fields = {
    'display_base': `₹${data.base_amount?.toLocaleString('en-IN', {minimumFractionDigits:2}) || '0.00'}`,
    'display_gst_type': data.gst_type === 'CGST_SGST' ? 'Intra-state (CGST + SGST)' : 'Inter-state (IGST)',
    'display_cgst': `₹${data.cgst?.toLocaleString('en-IN', {minimumFractionDigits:2}) || '0.00'}`,
    'display_sgst': `₹${data.sgst?.toLocaleString('en-IN', {minimumFractionDigits:2}) || '0.00'}`,
    'display_igst': `₹${data.igst?.toLocaleString('en-IN', {minimumFractionDigits:2}) || '0.00'}`,
    'display_total': `₹${data.total?.toLocaleString('en-IN', {minimumFractionDigits:2}) || '0.00'}`
  };
  for (const [id, val] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (el) { el.textContent = val; el.classList.add('animate-update'); setTimeout(() => el.classList.remove('animate-update'), 300); }
  }

  // Show/hide CGST/SGST vs IGST rows
  const cgstRow = document.getElementById('cgst_sgst_row');
  const sgstRow = document.getElementById('sgst_row');
  const igstRow = document.getElementById('igst_row');
  if (cgstRow) cgstRow.style.display = data.gst_type === 'CGST_SGST' ? '' : 'none';
  if (sgstRow) sgstRow.style.display = data.gst_type === 'CGST_SGST' ? '' : 'none';
  if (igstRow) igstRow.style.display = data.gst_type === 'IGST' ? '' : 'none';
}

function resetGSTDisplay() {
  ['display_base','display_cgst','display_sgst','display_igst','display_total'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '₹0.00';
  });
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'position-fixed bottom-0 end-0 m-3 p-3 bg-dark text-white rounded-3 shadow';
  toast.style.zIndex = '9999';
  toast.innerHTML = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// WhatsApp Share & Copy — driven by data-* attributes, NEVER inline onclick
// This prevents XSS: a client named  ', alert(1), '  cannot break out of a data attribute
function setupInvoiceActions() {
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;

    if (action === 'whatsapp') {
      handleWhatsAppShare(btn);
    }

    if (action === 'copy') {
      const link = btn.dataset.link || '';
      navigator.clipboard.writeText(link).then(() => showToast('✅ Link copied!'));
    }
  });
}

// Sends the invoice PDF straight into WhatsApp (or whichever app the user
// picks) via the native share sheet when the device/browser supports sharing
// files. Falls back to a wa.me text message with the view link when it
// doesn't (e.g. most desktop browsers, where WhatsApp Web has no public way
// to attach a file automatically).
async function handleWhatsAppShare(btn) {
  const invoiceNo = btn.dataset.invoice || '';
  const total     = btn.dataset.total   || '';
  const client    = btn.dataset.client  || '';
  const link      = btn.dataset.link    || '';
  const pdfUrl    = btn.dataset.pdf     || '';
  const pdfName   = btn.dataset.pdfName || `${invoiceNo || 'invoice'}.pdf`;

  const messageText = `Hi ${client}, please find your invoice ${invoiceNo} for ₹${total}. Sent via GSTLink`;

  if (pdfUrl && navigator.canShare) {
    const originalHTML = btn.innerHTML;
    try {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Preparing PDF...';

      const res = await fetch(pdfUrl, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('PDF fetch failed');
      const blob = await res.blob();
      const file = new File([blob], pdfName, { type: 'application/pdf' });

      if (navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], text: messageText });
        return; // user picked an app (or cancelled) — nothing else to do
      }
    } catch (err) {
      // AbortError means the user closed the share sheet — not a real error
      if (err && err.name === 'AbortError') return;
      console.error('WhatsApp file share failed, falling back to link:', err);
    } finally {
      btn.disabled = false;
      btn.innerHTML = originalHTML;
    }
  }

  // Fallback: desktop browsers / unsupported devices — open wa.me with the
  // message + view link, since there's no URL-based way to attach a file.
  const fallbackMsg = encodeURIComponent(
    `Hi ${client},\n\nPlease find your invoice *${invoiceNo}* for ₹${total}.\n\nView & download: ${link}\n\n_Sent via GSTLink_`
  );
  window.open(`https://wa.me/?text=${fallbackMsg}`, '_blank');
}

// Copy link (kept for any remaining callers)
function copyLink(text) {
  navigator.clipboard.writeText(text).then(() => showToast('✅ Link copied!'));
}

// Animate numbers on dashboard
function animateNumbers() {
  document.querySelectorAll('[data-count]').forEach(el => {
    const target = parseFloat(el.dataset.count);
    const isRupee = el.dataset.rupee === 'true';
    let start = 0; const duration = 1000;
    const step = target / (duration / 16);
    const timer = setInterval(() => {
      start += step;
      if (start >= target) { start = target; clearInterval(timer); }
      el.textContent = isRupee ? '₹' + start.toLocaleString('en-IN', {minimumFractionDigits:0, maximumFractionDigits:0}) : Math.round(start).toLocaleString('en-IN');
    }, 16);
  });
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  setupGSTCalculator();
  setupInvoiceActions();
  animateNumbers();
  
  // Auto-dismiss alerts
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(a => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(a);
      bsAlert?.close();
    });
  }, 5000);
});
