import Utils from './utils'

export type OnboardingVariant = 'control' | 'single_page'

// Which onboarding flow the user is in, from the onboarding_quickstart_flow
// flag the new flow is gated behind (#7738).
export const getOnboardingVariant = (): OnboardingVariant =>
  Utils.getFlagsmithHasFeature('onboarding_quickstart_flow')
    ? 'single_page'
    : 'control'
