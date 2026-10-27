// Display names for the source platforms the API identifies by key.
const PLATFORM_NAMES: Record<string, string> = {
  singstat: "SingStat",
  datagov: "Data.gov.sg",
  mom: "MOM",
};

export function platformName(key: string): string {
  return PLATFORM_NAMES[key] ?? key;
}
