import "./globals.css";
import { AuthProvider } from "./context/AuthContext";

export const metadata = {
  title: "ChatPDF — AI-Powered Document Assistant",
  description:
    "Upload any PDF and chat with it using AI. Get instant answers with citations powered by RAG.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
