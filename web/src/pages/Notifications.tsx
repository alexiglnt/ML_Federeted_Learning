import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { notifications as notificationsApi, type NotificationOut } from "../lib/api";

export default function Notifications() {
  const [items, setItems] = useState<NotificationOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    notificationsApi
      .list({ limit: 100 })
      .then(setItems)
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "Could not load notifications."),
      );
  }, []);

  async function markAllRead() {
    await notificationsApi.markAllRead();
    setItems(
      (prev) => prev?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null,
    );
  }

  async function clearAll() {
    await notificationsApi.clearAll();
    setItems([]);
  }

  async function removeNotification(id: number) {
    setItems((prev) => prev?.filter((n) => n.id !== id) ?? null);
    try {
      await notificationsApi.remove(id);
    } catch {
      // The list already dropped it; a failed delete is not worth restoring
      // it over and confusing the user mid-click.
    }
  }

  async function openNotification(notification: NotificationOut) {
    if (!notification.read_at) {
      setItems(
        (prev) =>
          prev?.map((n) =>
            n.id === notification.id ? { ...n, read_at: new Date().toISOString() } : n,
          ) ?? null,
      );
      try {
        await notificationsApi.markRead(notification.id);
      } catch {
        // Read state is a convenience, not a source of truth worth blocking on.
      }
    }
    if (notification.project_slug) navigate(`/projects/${notification.project_slug}`);
  }

  const unreadCount = items?.filter((n) => !n.read_at).length ?? 0;

  return (
    <section className="narrow">
      <div className="page-head">
        <h1>Notifications</h1>
        <span className="badge-row">
          {unreadCount > 0 && (
            <button type="button" className="ghost" onClick={markAllRead}>
              Mark all as read
            </button>
          )}
          {items && items.length > 0 && (
            <button type="button" className="ghost" onClick={clearAll}>
              Clear all
            </button>
          )}
        </span>
      </div>

      {error && <p className="muted">{error}</p>}
      {!error && !items && <p className="muted">Loading…</p>}
      {!error && items?.length === 0 && <p className="muted">No notifications yet.</p>}

      {items && items.length > 0 && (
        <ul className="notification-page-list">
          {items.map((notification) => (
            <li key={notification.id}>
              <div className="notification-row">
                <button
                  type="button"
                  className={`notification-item${notification.read_at ? "" : " unread"}`}
                  onClick={() => openNotification(notification)}
                >
                  <span className="notification-title">{notification.title}</span>
                  {notification.body && (
                    <span className="notification-body">{notification.body}</span>
                  )}
                  <span className="notification-time">
                    {new Date(notification.created_at).toLocaleString()}
                  </span>
                </button>
                <button
                  type="button"
                  className="notification-remove"
                  aria-label="Delete this notification"
                  title="Delete this notification"
                  onClick={() => removeNotification(notification.id)}
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
