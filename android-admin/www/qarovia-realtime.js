/**
 * Q-Arovia Real-Time & Unified Data Synchronization Engine
 * Multi-party low-latency WebSocket communication between
 * Patients, Hospitals, and Admins across Website, Android, and iOS.
 * Enforces standardized Event Taxonomy and Database-backed Catchup.
 */
(function (global) {
  "use strict";

  class QAroviaRealtimeClient {
    constructor() {
      this.ws = null;
      this.reconnectAttempts = 0;
      this.maxReconnectDelay = 8000;
      this.heartbeatTimer = null;
      this.options = null;
      this.listeners = new Set();
      this.isConnected = false;
      this.status = "disconnected";
      this.lastHeartbeatAck = Date.now();
      this.lastEventId = 0;
      this.isCatchingUp = false;
      this._bindLifecycleHooks();
    }

    getBaseHttpUrl() {
      const isLocal =
        typeof window !== "undefined" &&
        (window.location.hostname === "127.0.0.1" ||
         window.location.hostname === "localhost");
      return isLocal ? "http://127.0.0.1:8000" : "https://carepath-3q9q.onrender.com";
    }

    _setStatus(newStatus, detail = {}) {
      this.status = newStatus;
      this.isConnected = (newStatus === "connected");
      if (typeof this.options?.onStatusChange === "function") {
        try { this.options.onStatusChange(newStatus, detail); } catch (e) {}
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("qarovia:status", {
          detail: Object.assign({ status: newStatus }, detail)
        }));
      }
    }

    connect(options = {}) {
      this.options = Object.assign({}, this.options, options);
      const { role = "patient", token = "", phone = "", hospitalId = null } = this.options;

      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
        return;
      }

      this._setStatus(this.reconnectAttempts > 0 ? "reconnecting" : "connecting");

      // Determine WebSocket scheme & host (Single source of truth)
      const isLocal =
        typeof window !== "undefined" &&
        (window.location.hostname === "127.0.0.1" ||
         window.location.hostname === "localhost");
      const wsProtocol = (typeof window !== "undefined" && window.location.protocol === "https:")
        ? "wss:"
        : (isLocal ? "ws:" : "wss:");
      const wsHost = isLocal ? "127.0.0.1:8000" : "carepath-3q9q.onrender.com";

      const params = new URLSearchParams();
      if (token) params.set("token", token);
      if (role) params.set("role", role);
      if (phone) params.set("phone", phone);
      if (hospitalId) params.set("hospital_id", String(hospitalId));

      const wsUrl = `${wsProtocol}//${wsHost}/ws/messages?${params.toString()}`;
      console.log(`[Q-Arovia Realtime] Connecting to ${wsUrl} (${role})...`);

      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = async () => {
          console.log(`[Q-Arovia Realtime] Connected successfully (${role})`);
          this._setStatus("connected", { role });
          this.reconnectAttempts = 0;
          this._startHeartbeat();

          if (typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent("qarovia:connected", { detail: { role } }));
            window.dispatchEvent(new CustomEvent("qarovia:sync", { detail: { reason: "connected" } }));
          }

          // Trigger database-backed catchup for any missed events while disconnected
          await this.catchup();
        };

        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "pong") {
              this.lastHeartbeatAck = Date.now();
              return;
            }
            this._handleIncomingMessage(data);
          } catch (err) {
            console.warn("[Q-Arovia Realtime] Frame parsing failed:", err);
          }
        };

        this.ws.onerror = (err) => {
          console.warn("[Q-Arovia Realtime] WebSocket error:", err);
        };

        this.ws.onclose = (event) => {
          this._setStatus("disconnected", { code: event.code });
          this._stopHeartbeat();
          console.log(`[Q-Arovia Realtime] Disconnected (code: ${event.code}). Auto-reconnecting...`);
          if (typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent("qarovia:disconnected", { detail: { code: event.code } }));
          }
          this._scheduleReconnect();
        };
      } catch (err) {
        console.warn("[Q-Arovia Realtime] Connection initiation error:", err);
        this._setStatus("disconnected", { error: err });
        this._scheduleReconnect();
      }
    }

    _handleIncomingMessage(data) {
      if (!data) return;

      if (data.event_id) {
        const idNum = Number(data.event_id);
        if (!isNaN(idNum) && idNum > this.lastEventId) {
          this.lastEventId = idNum;
        }
      }

      console.log("[Q-Arovia Realtime] Message received:", data.event || data.type);
      this.listeners.forEach((fn) => {
        try {
          fn(data);
        } catch (e) {
          console.error("[Q-Arovia Realtime] Listener error:", e);
        }
      });

      if (typeof this.options?.onMessage === "function") {
        try { this.options.onMessage(data); } catch (e) {}
      }

      // Dispatch events for UI reactivity
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("qarovia:realtime", { detail: data }));
        if (data.type) {
          window.dispatchEvent(new CustomEvent(`qarovia:${data.type}`, { detail: data }));
        }
        if (data.type && data.action) {
          window.dispatchEvent(new CustomEvent(`qarovia:${data.type}:${data.action}`, { detail: data }));
        }
        if (data.event) {
          window.dispatchEvent(new CustomEvent(`qarovia:${data.event}`, { detail: data }));
        }
      }
    }

    async catchup() {
      if (this.isCatchingUp) return;
      this.isCatchingUp = true;
      try {
        const role = this.options?.role || "all";
        let targetId = null;
        if (role === "hospital") targetId = this.options?.hospitalId;
        else if (role === "patient") targetId = this.options?.phone;

        let url = `${this.getBaseHttpUrl()}/ws/events/sync?since_id=${this.lastEventId || 0}&limit=100`;
        if (role && role !== "all") {
          url += `&channel_type=${encodeURIComponent(role)}`;
        }
        if (targetId) {
          url += `&target_id=${encodeURIComponent(targetId)}`;
        }

        const headers = {};
        if (this.options?.token) {
          headers["Authorization"] = `Bearer ${this.options.token}`;
        }

        const res = await fetch(url, { headers });
        if (res.ok) {
          const body = await res.json();
          const events = body.events || [];
          for (const ev of events) {
            if (ev.payload) {
              const p = ev.payload;
              if (ev.id) p.event_id = ev.id;
              this._handleIncomingMessage(p);
            }
            if (ev.id && ev.id > this.lastEventId) {
              this.lastEventId = ev.id;
            }
          }
          if (body.latest_id && body.latest_id > this.lastEventId) {
            this.lastEventId = body.latest_id;
          }
        }
      } catch (e) {
        console.warn("[Q-Arovia Realtime] Catchup sync failed:", e);
      } finally {
        this.isCatchingUp = false;
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("qarovia:sync_complete"));
        }
      }
    }

    _bindLifecycleHooks() {
      if (typeof window === "undefined" || typeof document === "undefined") return;

      const triggerResume = async () => {
        if (!this.isConnected && this.options) {
          console.log("[Q-Arovia Realtime] App resumed/visible, reconnecting WebSocket...");
          this.connect(this.options);
        } else if (this.isConnected) {
          await this.catchup();
        }
        window.dispatchEvent(new CustomEvent("qarovia:resume"));
        window.dispatchEvent(new CustomEvent("qarovia:sync", { detail: { reason: "resume" } }));
      };

      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
          triggerResume();
        }
      });

      window.addEventListener("focus", triggerResume);
      window.addEventListener("online", () => {
        console.log("[Q-Arovia Realtime] Network online, initiating immediate sync...");
        this._setStatus("reconnecting", { reason: "online" });
        triggerResume();
      });
      window.addEventListener("offline", () => {
        this._setStatus("offline");
      });
      window.addEventListener("pageshow", (e) => {
        if (e.persisted) {
          triggerResume();
        }
      });
    }

    _startHeartbeat() {
      this._stopHeartbeat();
      this.heartbeatTimer = setInterval(() => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 25000);
    }

    _stopHeartbeat() {
      if (this.heartbeatTimer) {
        clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;
      }
    }

    _scheduleReconnect() {
      this.reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts - 1), this.maxReconnectDelay);
      setTimeout(() => {
        if (!this.isConnected && this.options) {
          this.connect(this.options);
        }
      }, delay);
    }

    on(listener) {
      if (typeof listener === "function") {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
      }
      return () => {};
    }

    send(data) {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(data));
        return true;
      }
      return false;
    }
  }

  global.QAroviaRealtime = new QAroviaRealtimeClient();
})(typeof window !== "undefined" ? window : this);
