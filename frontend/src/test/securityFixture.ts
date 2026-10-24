// Security findings for the map's tests (D31): what /security answers for the trip planner.
export const KEY_FINDING = {
  id: "key_in_code-config-py-23", kind: "key_in_code", level: "high", title: "A Google API key is written in the code",
  ref: "config.py:23", line: 23, dep_id: "api-nominatim", first_line: 22,
  excerpt: ["# map image for the day", 'GOOGLE_STATIC_MAPS_KEY = "[REDACTED]"', 'STATIC_MAP_URL = "https://maps.googleapis.com/x"'],
  fix: "Move it to .env and read it from the environment. Then replace the key: it may be in your git history.",
  prompt: "In config.py:23, a Google API key is written in the code. Move it to an environment variable named GOOGLE_STATIC_MAPS_KEY.",
};
export const HTTP_FINDING = {
  id: "plain_http-config-py-18", kind: "plain_http", level: "medium", title: "ip-api.com is called over http://",
  ref: "config.py:18", line: 18, dep_id: null, first_line: 18, excerpt: ['IP_API_URL = "http://ip-api.com/json/"'],
  fix: "Use https:// if the service offers it.", prompt: "Change it to https.",
};
export const SECURITY = { repo: "trip-planner", scanned: true, summary: { high: 1, medium: 1 }, findings: [KEY_FINDING, HTTP_FINDING] };
