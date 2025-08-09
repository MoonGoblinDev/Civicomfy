// Centralized feedback utilities: toasts and icon CSS

export class Feedback {
  constructor(toastElement) {
    this.toastElement = toastElement || null;
    this.toastTimeout = null;
  }

  ensureFontAwesome() {
    if (!document.getElementById('civitai-fontawesome-link')) {
      const faLink = document.createElement('link');
      faLink.id = 'civitai-fontawesome-link';
      faLink.rel = 'stylesheet';
      faLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css';
      faLink.integrity = 'sha512-1ycn6IcaQQ40/MKBW2W4Rhis/DbILU74C1vSrLJxCq57o941Ym01SwNsOMqvEBFlcgUa6xLiPY/NS5R+E6ztJQ==';
      faLink.crossOrigin = 'anonymous';
      faLink.referrerPolicy = 'no-referrer';
      document.head.appendChild(faLink);
    }
  }

  show(message, type = 'info', duration = 3000) {
    if (!this.toastElement) return;
    if (this.toastTimeout) {
      clearTimeout(this.toastTimeout);
      this.toastTimeout = null;
    }
    const valid = ['info', 'success', 'error', 'warning'];
    const toastType = valid.includes(type) ? type : 'info';

    this.toastElement.textContent = message;
    this.toastElement.className = 'civitai-toast';
    this.toastElement.classList.add(toastType);
    requestAnimationFrame(() => this.toastElement.classList.add('show'));
    this.toastTimeout = setTimeout(() => {
      this.toastElement.classList.remove('show');
      this.toastTimeout = null;
    }, duration);
  }
}

