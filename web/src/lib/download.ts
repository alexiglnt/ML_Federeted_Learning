/* Handing a fetched blob to the browser as a file.
 *
 * Kept out of lib/api.ts, which is deliberately the one file that describes
 * everything leaving the page over the network. This touches only the DOM.
 */

/** Save a blob under `filename`, then release the object URL.
 *
 * The revoke is not housekeeping: without it the blob stays in memory for the
 * life of the document, and a contributor's dataset is exactly the kind of
 * thing that should not linger there after it has been written to disk.
 */
export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
