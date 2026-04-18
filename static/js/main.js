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

// AI Contract Parser
function setupContractParser() {
  const btn = document.getElementById('parseContractBtn');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const text = document.getElementById('contractText')?.value || '';
    if (text.length < 20) { alert('Please paste more contract text.'); return; }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Parsing with AI...';

    try {
      const res = await fetch('/ai/parse-contract', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text})
      });
      const data = await res.json();
      if (data.error && !data.client_name) { alert('Parse error: ' + data.error); return; }

      // Fill form fields
      if (data.amount) setVal('amount', data.amount);
      if (data.description) setVal('description', data.description);
      if (data.hsn_sac) setVal('hsn_sac', data.hsn_sac);

      document.getElementById('contractModal')?.querySelector('[data-bs-dismiss="modal"]')?.click();
      
      // Show parsed result
      if (data.client_name || data.client_gstin) {
        showToast(`✅ AI extracted: ${data.client_name || ''} ${data.client_gstin ? '• GSTIN: '+data.client_gstin : ''}`);
      }

      // Trigger GST recalculation
      document.getElementById('amount')?.dispatchEvent(new Event('input'));

    } catch(e) {
      alert('Failed to parse contract. Please try again or check your Groq API key.');
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-stars me-2"></i>Parse with AI';
    }
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
      // Values read from DOM data attributes — never interpolated into JS at render time
      const invoiceNo = btn.dataset.invoice || '';
      const total    = btn.dataset.total   || '';
      const client   = btn.dataset.client  || '';
      const link     = btn.dataset.link    || '';
      const msg = encodeURIComponent(
        `Hi ${client},\n\nPlease find your invoice *${invoiceNo}* for ₹${total}.\n\nView & download: ${link}\n\n_Sent via GSTLink_`
      );
      window.open(`https://wa.me/?text=${msg}`, '_blank');
    }

    if (action === 'copy') {
      const link = btn.dataset.link || '';
      navigator.clipboard.writeText(link).then(() => showToast('✅ Link copied!'));
    }
  });
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
  setupContractParser();
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
