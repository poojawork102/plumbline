export function money(value, currency) {
  if (value === null || value === undefined) return "—";
  const n = Math.round(Number(value));
  if (currency === "INR") return "₹" + n.toLocaleString("en-IN");
  return "$" + n.toLocaleString("en-US");
}

export const THEME_COLORS = {
  shower: "#5A7D8C",
  toilet: "#F4F2EC",
  vanity: "#8B7355",
  faucet: "#B89758",
};
