export function roleHome(role?: string): string {
  switch (role) {
    case "SUPER_ADMIN":
      return "/admin";
    case "WARD_REPRESENTATIVE":
      return "/ward-rep";
    case "OFFICER":
    case "ADMIN":
      return "/officer";
    case "FIELD_WORKER":
      return "/work";
    default:
      return "/dashboard";
  }
}