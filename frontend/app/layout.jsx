import "./globals.css";

export const metadata = { title: "Persona", description: "A personal assistant you can text or call." };
export const viewport = { width: "device-width", initialScale: 1, themeColor: "#000000" };

export default function RootLayout({ children }) {
  return <html lang="en" className="dark"><body>{children}</body></html>;
}
