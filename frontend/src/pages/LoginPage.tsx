import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import logoImg from "@/assets/logo.png";
export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  // Registration modal
  const [showRegister, setShowRegister] = useState(false);
  const [regUsername, setRegUsername] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirm, setRegConfirm] = useState("");
  const [regError, setRegError] = useState("");
  const [regSuccess, setRegSuccess] = useState("");

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await login(username, password);
      navigate("/dashboard");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || "Login failed";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setRegError("");
    setRegSuccess("");
    if (regPassword !== regConfirm) {
      setRegError("Passwords do not match");
      return;
    }
    try {
      await register(regUsername, regPassword, regEmail || undefined);
      setRegSuccess("Account created! You can now log in.");
      setTimeout(() => setShowRegister(false), 1500);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || "Registration failed";
      setRegError(msg);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-50 dark:from-[#202124] dark:to-[#292a2d] p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-3 mb-2">
            <img src={logoImg} alt="ParseMyLog AI" className="h-10 w-10" />
            <h1 className="text-3xl font-bold">ParseMyLog AI</h1>
          </div>
          <p className="text-muted-foreground text-sm">Advanced log analysis platform</p>
        </div>

        {/* Login Card */}
        <div className="bg-card border border-border rounded-2xl shadow-sm p-6">
          <h2 className="text-xl font-semibold mb-4">Sign In</h2>

          {error && (
            <div className="mb-4 p-3 bg-destructive/10 text-destructive rounded-lg text-sm">{error}</div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="Enter username"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                placeholder="Enter password"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 px-4 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {isLoading ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              onClick={() => setShowRegister(true)}
              className="text-sm text-primary hover:underline"
            >
              Create an account
            </button>
          </div>
        </div>
      </div>

      {/* Registration Modal */}
      {showRegister && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">Register New Account</h3>

            {regError && (
              <div className="mb-3 p-3 bg-destructive/10 text-destructive rounded-lg text-sm">{regError}</div>
            )}
            {regSuccess && (
              <div className="mb-3 p-3 bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400 rounded-lg text-sm">{regSuccess}</div>
            )}

            <form onSubmit={handleRegister} className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">Username</label>
                <input
                  type="text"
                  value={regUsername}
                  onChange={(e) => setRegUsername(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Email (optional)</label>
                <input
                  type="email"
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Password</label>
                <input
                  type="password"
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Confirm Password</label>
                <input
                  type="password"
                  value={regConfirm}
                  onChange={(e) => setRegConfirm(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  required
                />
              </div>
              <div className="flex gap-2 pt-2">
                <button
                  type="submit"
                  className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90"
                >
                  Create Account
                </button>
                <button
                  type="button"
                  onClick={() => setShowRegister(false)}
                  className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
