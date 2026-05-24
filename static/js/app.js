// GSTLink – App JavaScript

// Auto-dismiss alerts after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    document.querySelectorAll('.alert.fade.show').forEach(function(alert) {
      new bootstrap.Alert(alert).close();
    });
  }, 5000);

  // GSTIN auto-format (uppercase, max 15)
  document.querySelectorAll('input[name="gstin"], input[name="client_gstin"]').forEach(function(el) {
    el.addEventListener('input', function() {
      this.value = this.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 15);
    });
  });

  // IFSC auto-uppercase
  document.querySelectorAll('input[name="ifsc_code"]').forEach(function(el) {
    el.addEventListener('input', function() {
      this.value = this.value.toUpperCase();
    });
  });

  // PAN auto-uppercase
  document.querySelectorAll('input[name="pan"]').forEach(function(el) {
    el.addEventListener('input', function() {
      this.value = this.value.toUpperCase().slice(0, 10);
    });
  });
});
