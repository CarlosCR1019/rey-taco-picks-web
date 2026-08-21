export type Membership = {
  status: string;
  current_period_end: string | null;
};

export function isMembershipActive(value: Membership | null): boolean {
  return Boolean(
    value
    && ['active', 'trialing'].includes(value.status)
    && value.current_period_end
    && Date.parse(value.current_period_end) > Date.now()
  );
}
