/**
 * CarePath Real-Time Messaging Engine
 * Multi-party low-latency WebSocket communication between
 * Patients, Hospitals, and Admins.
 */
(function (global) {
  "use strict";

  class CarePathRealtimeClient {
    constructor() {
      this.ws = null;
      this.reconnectAttempts = 0;
      this.maxReconnectDelay = 10000;
      this.heartbeatTimer = null;
      this.options = null;
      this.listeners = new Set();
      this.isConnected = false;
      this.lastHeartbeatAck = Date.now();
    }

    /**
     * Connect to the CarePath WebSocket message bus
     * @param {Object} options
     * @param {string} options.role - "patient", "hospital", or "admin"
     * @param {string} [options.token] - JWT token for auth
     * @param {string} [options.phone] - Patient phone number
     * @param {number|string} [options.hospitalId] - Hospital ID
     * @param {Function} [options.onMessage] - Message received callback
     * @param {Function} [options.onStatusChange] - Status changed callback
     */
    connect(options = {}) {
      this.options = Object.assign({}, this.options, options);
      const { role = "patient", token = "", phone = "", hospitalId = null } = this.options;

      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
        return;
      }

      // Determine WebSocket scheme & host
      const isLocal =
        window.location.hostname === "127.0.0.1" ||
        window.location.hostname === "localhost";
      const wsProtocol = window.location.protocol === "https:" ? "wss:" : (isLocal ? "ws:" : "wss:");
      const wsHost = isLocal ? "127.0.0.1:8000" : "carepath-3q9q.onrender.com";

      const params = new URLSearchParams();
      if (token) params.set("token", token);
      if (role) params.set("role", role);
      if (phone) params.set("phone", phone);
      if (hospitalId) params.set("hospital_id", String(hospitalId));

      const wsUrl = `${wsProtocol}//${wsHost}/ws/messages?${params.toString()}`;
      console.log(`[CarePath Realtime] Connecting to ${wsUrl} (${role})...`);

      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log(`[CarePath Realtime] Connected successfully (${role})`);
          this.isConnected = true;
          this.reconnectAttempts = 0;
          this._startHeartbeat();
          if (typeof this.options.onStatusChange === "function") {
            this.options.onStatusChange("connected");
          }
        };

        this.ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "pong") {
              this.lastHeartbeatAck = Date.now();
              return;
            }

            console.log("[CarePath Realtime] Message received:", data.type);
            this.listeners.forEach((fn) => {
              try {
                fn(data);
              } catch (e) {
                console.error("[CarePath Realtime] Listener error:", e);
              }
            });

            if (typeof this.options.onMessage === "function") {
              this.options.onMessage(data);
            }
          } catch (err) {
            console.warn("[CarePath Realtime] Frame parsing failed:", err);
          }
        };

        this.ws.onerror = (err) => {
          console.warn("[CarePath Realtime] WebSocket error:", err);
        };

        this.ws.onclose = (event) => {
          this.isConnected = false;
          this._stopHeartbeat();
          console.log(`[CarePath Realtime] Disconnected (code: ${event.code}). Auto-reconnecting...`);
          if (typeof this.options.onStatusChange === "function") {
            this.options.onStatusChange("disconnected");
          }
          this._scheduleReconnect();
        };
      } catch (err) {
        console.warn("[CarePath Realtime] Connection initiation error:", err);
        this._scheduleReconnect();
      }
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

  global.CarePathRealtime = new CarePathRealtimeClient();
})(typeof window !== "undefined" ? window : this);
