import { useState } from "react";
import { Link2, ShieldCheck } from "lucide-react";
import { backendOrigin, configureConnection } from "../connection";
import { errorMessage } from "../format";
import { Dialog } from "./Dialog";

export function ConnectionSettings({ onClose }: { onClose: () => void }) {
  const [origin, setOrigin] = useState(backendOrigin());
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  return (
    <Dialog
      title="Backend connection"
      className="worker-dialog"
      onClose={onClose}
    >
      <Link2 size={24} />
      <h2>Backend connection</h2>
      <p>
        The frontend runs here. The controller and Docker workers run on your
        PC.
      </p>
      <label htmlFor="backend-origin">Backend HTTPS address</label>
      <input
        id="backend-origin"
        type="url"
        value={origin}
        onChange={(event) => setOrigin(event.target.value)}
        placeholder="https://your-address.ngrok-free.dev"
      />
      <p className="worker-origin">
        Leave empty for the same local controller. Use only an address you
        control; your key is sent to this server.
      </p>
      <label htmlFor="backend-key">Owner access key</label>
      <input
        id="backend-key"
        type="password"
        autoComplete="off"
        value={key}
        onChange={(event) => setKey(event.target.value)}
        placeholder="From your local demo setup"
      />
      <p className="worker-origin">
        <ShieldCheck size={13} /> The key stays in this page’s memory and is
        cleared when the page reloads. It is never stored in Vercel or browser
        storage.
      </p>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button className="button secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          className="button primary"
          onClick={() => {
            try {
              configureConnection(origin, key);
              onClose();
            } catch (error) {
              setError(errorMessage(error));
            }
          }}
        >
          Connect backend
        </button>
      </div>
    </Dialog>
  );
}
