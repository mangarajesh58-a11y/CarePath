/**
 * CarePath Unified Permissions & Notifications Engine
 * Handles Google Chrome / Web site permissions for:
 *  - Native Browser Push / Screen & Sound Notifications
 *  - Camera Access & Live Prescription Scanner
 *  - Photo & Document Upload Fallbacks
 */

(function (window) {
  'use strict';

  // ----------------------------------------------------
  // Audio Synthesizer for Immediate Auditory Cues
  // ----------------------------------------------------
  let audioCtx = null;
  function getAudioContext() {
    if (!audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) audioCtx = new AudioContext();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
    return audioCtx;
  }

  function playAlertChime(type = 'success') {
    try {
      const ctx = getAudioContext();
      if (!ctx) return;
      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.connect(gain);
      gain.connect(ctx.destination);

      if (type === 'urgent') {
        // High attention two-tone chime for OPD token call
        osc.frequency.setValueAtTime(587.33, now); // D5
        osc.frequency.setValueAtTime(880.00, now + 0.15); // A5
        gain.gain.setValueAtTime(0.3, now);
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.6);
        osc.start(now);
        osc.stop(now + 0.6);
      } else {
        // Soft positive chime for general alerts & replies
        osc.frequency.setValueAtTime(523.25, now); // C5
        osc.frequency.setValueAtTime(659.25, now + 0.12); // E5
        gain.gain.setValueAtTime(0.2, now);
        gain.gain.exponentialRampToValueAtTime(0.01, now + 0.45);
        osc.start(now);
        osc.stop(now + 0.45);
      }
    } catch (e) {
      // Audio autoplay policy fallback
    }
  }

  // ----------------------------------------------------
  // CarePath Native Notification Engine
  // ----------------------------------------------------
  const CarePathNotifications = {
    isSupported() {
      return 'Notification' in window;
    },

    getStatus() {
      if (!this.isSupported()) return 'unsupported';
      return Notification.permission; // 'default', 'granted', 'denied'
    },

    async requestPermission(onGranted = null, onDenied = null) {
      if (!this.isSupported()) {
        alert('Browser notifications are not supported on this device/browser.');
        return 'unsupported';
      }

      try {
        const result = await Notification.requestPermission();
        if (result === 'granted') {
          localStorage.setItem('carepath_notif_enabled', 'true');
          sessionStorage.setItem('carepath_notif_banner_dismissed', 'true');
          this.hideBanner();
          this.updateUiBadges(true);
          playAlertChime('success');

          // Send immediate welcome test notification
          this.send('🔔 CarePath Live Alerts Active', {
            body: 'You will receive instant alerts when your doctor calls your token or hospital replies.',
            tag: 'carepath-welcome',
          });

          if (typeof onGranted === 'function') onGranted();
        } else if (result === 'denied') {
          localStorage.setItem('carepath_notif_enabled', 'false');
          this.updateUiBadges(false);
          this.showBlockedModal('notification');
          if (typeof onDenied === 'function') onDenied();
        }
        return result;
      } catch (err) {
        console.warn('Notification permission request error:', err);
        return Notification.permission;
      }
    },

    send(title, options = {}) {
      if (!this.isSupported() || Notification.permission !== 'granted') {
        console.info('Notification skipped (permission:', Notification.permission, ')');
        return null;
      }

      // Default notification styling
      const defaults = {
        icon: 'carepath-ai-small.png',
        badge: 'carepath-ai-small.png',
        vibrate: [200, 100, 200, 100, 300],
        silent: false,
        requireInteraction: options.urgent || false,
      };

      const finalOptions = Object.assign({}, defaults, options);

      // Play complementary sound chime
      playAlertChime(options.urgent ? 'urgent' : 'success');

      try {
        const notif = new Notification(title, finalOptions);
        notif.onclick = function (e) {
          e.preventDefault();
          window.focus();
          if (typeof options.onClick === 'function') {
            options.onClick();
          }
          notif.close();
        };
        return notif;
      } catch (e) {
        // Fallback for mobile Android Chrome requiring ServiceWorker showNotification
        if (navigator.serviceWorker && navigator.serviceWorker.ready) {
          navigator.serviceWorker.ready.then((reg) => {
            reg.showNotification(title, finalOptions);
          }).catch(() => {});
        }
        return null;
      }
    },

    updateUiBadges(isGranted) {
      document.querySelectorAll('.notif-status-badge').forEach((el) => {
        if (isGranted) {
          el.textContent = 'Alerts: ON';
          el.style.background = '#dcfce7';
          el.style.color = '#15803d';
          el.style.borderColor = '#86efac';
        } else {
          el.textContent = 'Alerts: OFF';
          el.style.background = '#fef2f2';
          el.style.color = '#b91c1c';
          el.style.borderColor = '#fecaca';
        }
      });
    },

    initBanner(containerId = 'carepathNotificationBannerContainer') {
      if (!this.isSupported()) return;
      if (Notification.permission === 'granted') {
        this.updateUiBadges(true);
        return;
      }
      if (sessionStorage.getItem('carepath_notif_banner_dismissed') === 'true') {
        return;
      }

      let container = document.getElementById(containerId);
      if (!container) {
        container = document.createElement('div');
        container.id = containerId;
        const pageHeader = document.querySelector('.topbar') || document.querySelector('.mobile-app-header') || document.body;
        if (pageHeader && pageHeader.parentNode) {
          pageHeader.parentNode.insertBefore(container, pageHeader.nextSibling);
        } else {
          document.body.prepend(container);
        }
      }

      container.innerHTML = `
        <div id="carepathNotifBanner" style="
          background: linear-gradient(135deg, #eff6ff 0%, #e0f2fe 100%);
          border: 1px solid #bfdbfe;
          border-radius: 14px;
          padding: 12px 16px;
          margin: 10px auto 14px;
          max-width: 600px;
          box-shadow: 0 4px 14px rgba(2, 132, 199, 0.12);
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          animation: cpSlideDown 0.3s ease-out;
        ">
          <div style="display: flex; align-items: center; gap: 10px;">
            <div style="font-size: 24px; animation: tokenLivePulse 2s infinite;">🔔</div>
            <div>
              <div style="font-weight: 800; font-size: 13.5px; color: #0369a1; line-height: 1.3;">Enable Live Alerts</div>
              <div style="font-size: 11.5px; color: #475569; margin-top: 1px;">Get sound alerts when your OPD token is called & hospital replies</div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
            <button type="button" onclick="CarePathPermissions.requestNotificationPermission()" style="
              background: #0284c7;
              color: white;
              border: none;
              border-radius: 8px;
              padding: 7px 12px;
              font-size: 12px;
              font-weight: 800;
              cursor: pointer;
              box-shadow: 0 2px 6px rgba(2, 132, 199, 0.3);
            ">Enable</button>
            <button type="button" onclick="CarePathPermissions.dismissBanner()" aria-label="Dismiss" style="
              background: transparent;
              border: none;
              color: #64748b;
              font-size: 18px;
              padding: 4px 8px;
              cursor: pointer;
              line-height: 1;
            ">&times;</button>
          </div>
        </div>
      `;
    },

    hideBanner() {
      const banner = document.getElementById('carepathNotifBanner');
      if (banner) banner.remove();
    },

    dismissBanner() {
      sessionStorage.setItem('carepath_notif_banner_dismissed', 'true');
      this.hideBanner();
    },

    showBlockedModal(type = 'notification') {
      const isNotif = type === 'notification';
      const modalId = isNotif ? 'carepathNotifBlockedModal' : 'carepathCameraBlockedModal';
      let modal = document.getElementById(modalId);

      if (!modal) {
        modal = document.createElement('div');
        modal.id = modalId;
        modal.style.cssText = 'display: flex; position: fixed; inset: 0; background: rgba(15, 23, 42, 0.75); z-index: 3000000; backdrop-filter: blur(4px); align-items: center; justify-content: center; padding: 20px; box-sizing: border-box;';
        
        const title = isNotif ? 'Notifications Blocked in Browser' : 'Camera Access Blocked in Browser';
        const icon = isNotif ? '🔔⚠️' : '📷⚠️';
        const desc = isNotif 
          ? 'Your browser has notifications blocked. To receive live token calls & hospital messages:' 
          : 'Your browser blocked camera access. To scan doctor prescriptions directly:';
        const step2 = isNotif ? 'Notifications' : 'Camera';

        modal.innerHTML = `
          <div style="background: white; border-radius: 20px; max-width: 380px; width: 100%; padding: 24px; box-shadow: 0 25px 50px rgba(0,0,0,0.3); text-align: center; box-sizing: border-box; animation: cpSlideDown 0.25s ease;">
            <div style="font-size: 38px; margin-bottom: 8px;">${icon}</div>
            <h3 style="margin: 0 0 8px; font-size: 18px; color: #0f172a; font-weight: 800;">${title}</h3>
            <p style="margin: 0 0 16px; font-size: 13px; color: #64748b; line-height: 1.5; text-align: left;">
              ${desc}
            </p>
            <div style="background: #f8fafc; border: 1.5px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; text-align: left; font-size: 12.5px; color: #334155; line-height: 1.55; margin-bottom: 18px;">
              <div style="margin-bottom: 8px; font-weight: 700; color: #0f172a;">📱 In Google Chrome or Android Settings:</div>
              <div>1. Tap <strong>🔒 (lock/tune icon)</strong> or <strong>⋮ (3 dots)</strong> in address bar.</div>
              <div>2. Open <strong>Site Settings</strong> ➔ <strong>${step2}</strong> ➔ <strong>Allow</strong>.</div>
              <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #cbd5e1; font-size: 12px; color: #64748b;">
                Then tap <strong>Reload Page</strong> to activate.
              </div>
            </div>
            <div style="display: flex; gap: 10px;">
              <button type="button" onclick="document.getElementById('${modalId}').remove()" style="flex: 1; padding: 11px; background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; border-radius: 10px; font-weight: 700; font-size: 13px; cursor: pointer;">
                Close
              </button>
              <button type="button" onclick="location.reload()" style="flex: 1.3; padding: 11px; background: #0284c7; color: white; border: none; border-radius: 10px; font-weight: 800; font-size: 13px; cursor: pointer; box-shadow: 0 4px 12px rgba(2,132,199,0.3);">
                🔄 Reload Page
              </button>
            </div>
          </div>
        `;
        document.body.appendChild(modal);
      } else {
        modal.style.display = 'flex';
      }
    }
  };

  // ----------------------------------------------------
  // CarePath Camera & Upload Engine
  // ----------------------------------------------------
  const CarePathCamera = {
    async requestCameraStream(facingMode = 'environment') {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Camera streaming is not supported in this browser.');
      }
      try {
        return await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingMode },
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
        });
      } catch (err) {
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          CarePathNotifications.showBlockedModal('camera');
        }
        throw err;
      }
    },

    triggerFileInput(inputId) {
      const input = document.getElementById(inputId);
      if (input) input.click();
    }
  };

  // Expose global namespace
  window.CarePathPermissions = {
    requestNotificationPermission: () => CarePathNotifications.requestPermission(),
    sendNotification: (title, opts) => CarePathNotifications.send(title, opts),
    initNotificationBanner: (cId) => CarePathNotifications.initBanner(cId),
    dismissBanner: () => CarePathNotifications.dismissBanner(),
    showBlockedModal: (type) => CarePathNotifications.showBlockedModal(type),
    requestCameraStream: (facing) => CarePathCamera.requestCameraStream(facing),
    triggerFileInput: (id) => CarePathCamera.triggerFileInput(id),
    playChime: (type) => playAlertChime(type),
    getStatus: () => CarePathNotifications.getStatus(),
  };

  // Auto-init banner when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => CarePathNotifications.initBanner());
  } else {
    CarePathNotifications.initBanner();
  }

})(window);
