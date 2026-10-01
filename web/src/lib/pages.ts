// Whether a web page can open in a window (docs/design-handoff S3.P4.007): the gateway fetches it once, following
// redirects, and says yes only for a 2xx with nothing that forbids framing. Asked once per address. With no gateway
// (the web build) nothing can be checked, so every page opens outside.
const answers = new Map<string, Promise<boolean>>()

export function framable(url: string): Promise<boolean> {
  let answer = answers.get(url)
  if (!answer) {
    answer = fetch(`/__chat/frame?url=${encodeURIComponent(url)}`)
      .then((res) => (res.ok ? res.json() : { framable: false }))
      .then((data: { framable?: unknown }) => data.framable === true)
      .catch(() => false)
    answers.set(url, answer)
  }
  return answer
}
