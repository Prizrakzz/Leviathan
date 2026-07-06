import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getProfile, putProfile, type Profile, type ProfileUpdate } from './client';
import { useSession } from '@/store/session';

/** The signed-in user's profile (6.6). Gated on session readiness so it never races the OIDC restore
 *  (mock/local builds are ready immediately). Drives the Settings modal + the onboarding gate. */
export function useProfile() {
  const ready = useSession((s) => s.ready);
  return useQuery<Profile>({ queryKey: ['profile'], queryFn: getProfile, enabled: ready, staleTime: 60_000 });
}

/** Persist a partial profile update; primes the cache with the server-normalized result on success. */
export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (update: ProfileUpdate) => putProfile(update),
    onSuccess: (p) => qc.setQueryData(['profile'], p),
  });
}
