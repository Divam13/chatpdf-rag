"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "../lib/api";
import { useAuth } from "../context/AuthContext";
import styles from "./login.module.css";

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { loginUser } = useAuth();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      let data;
      if (isRegister) {
        data = await register(email, name, password);
      } else {
        data = await login(email, password);
      }
      loginUser(data.user, data.access_token);
      router.push("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.container}>
      {/* Background glow effects */}
      <div className={styles.bgGlow1} />
      <div className={styles.bgGlow2} />

      <div className={styles.card}>
        <div className={styles.logo}>
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
            <rect width="40" height="40" rx="10" fill="url(#g1)" />
            <path d="M12 28V12h8a6 6 0 110 12h-8" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M16 20h4l4 8" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
            <defs>
              <linearGradient id="g1" x1="0" y1="0" x2="40" y2="40">
                <stop stopColor="#7c5cfc" />
                <stop offset="1" stopColor="#a78bfa" />
              </linearGradient>
            </defs>
          </svg>
          <span className={styles.logoText}>ChatPDF</span>
        </div>

        <h1 className={styles.title}>
          {isRegister ? "Create your account" : "Welcome back"}
        </h1>
        <p className={styles.subtitle}>
          {isRegister
            ? "Start chatting with your documents in seconds"
            : "Sign in to continue to your documents"}
        </p>

        <form onSubmit={handleSubmit} className={styles.form}>
          {isRegister && (
            <div className={styles.field}>
              <label htmlFor="name">Full Name</label>
              <input
                id="name"
                type="text"
                placeholder="John Doe"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
          )}
          <div className={styles.field}>
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className={styles.field}>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>

          {error && <div className={styles.error}>{error}</div>}

          <button
            type="submit"
            className={styles.submitBtn}
            disabled={loading}
          >
            {loading ? (
              <span className={styles.spinner} />
            ) : isRegister ? (
              "Create Account"
            ) : (
              "Sign In"
            )}
          </button>
        </form>

        <div className={styles.toggle}>
          {isRegister ? "Already have an account?" : "Don't have an account?"}{" "}
          <button onClick={() => { setIsRegister(!isRegister); setError(""); }}>
            {isRegister ? "Sign in" : "Sign up"}
          </button>
        </div>
      </div>
    </div>
  );
}
