import { useAuth } from "../contexts/AuthContext";

export default function Profile() {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Profile</h1>
      <p className="mt-1 text-sm text-slate-500">Your account details.</p>

      <div className="mt-6 max-w-md rounded-lg border border-slate-200 bg-white p-5">
        <dl className="space-y-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-500">Full name</dt>
            <dd className="font-medium text-slate-900">{user.full_name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Email</dt>
            <dd className="font-medium text-slate-900">{user.email}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Role</dt>
            <dd className="font-medium text-slate-900">{user.role}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Status</dt>
            <dd className="font-medium text-slate-900">{user.is_active ? "Active" : "Inactive"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Member since</dt>
            <dd className="font-medium text-slate-900">
              {new Date(user.created_at).toLocaleDateString()}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
