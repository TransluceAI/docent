'use client';

import { Loader2, ChevronLeft, ChevronRight } from 'lucide-react';
import { Suspense, useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

import {
  Carousel,
  CarouselContent,
  CarouselItem,
  type CarouselApi,
} from '@/components/ui/carousel';

import { signup } from '../services/authService';
import { useUserContext } from '../contexts/UserContext';

function SignupPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setUser } = useUserContext();
  const redirectParam = searchParams.get('redirect') || '';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [carouselApi, setCarouselApi] = useState<CarouselApi | null>(null);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [totalSlides, setTotalSlides] = useState(0);

  useEffect(() => {
    if (!carouselApi) return;

    const update = () => {
      setCurrentSlide(carouselApi.selectedScrollSnap());
      setTotalSlides(carouselApi.scrollSnapList().length);
    };

    update();
    carouselApi.on('select', update);
    carouselApi.on('reInit', update);

    return () => {
      carouselApi.off('select', update);
      carouselApi.off('reInit', update);
    };
  }, [carouselApi]);

  const videoItems = [
    {
      src: 'https://transluce-videos.s3.us-east-1.amazonaws.com/docent-landing-page/features-1-refinement.mp4',
      description: (
        <>
          <div className="font-semibold text-lg">1. Create a rubric</div>
          <div className="text-sm space-y-3 text-muted-foreground">
            <p>
              Ask any question about your agent, such as &quot;where is it
              reward hacking?&quot; or &quot;why did it fail?&quot;
            </p>
            <p>
              Docent first converts it into a precise <b>behavior rubric</b> by
              reading through your data, asking questions about ambiguities, and
              suggesting concrete re-writes based on your feedback.
            </p>
          </div>
        </>
      ),
    },
    {
      src: 'https://transluce-videos.s3.us-east-1.amazonaws.com/docent-landing-page/features-2-exploring-results.mp4',
      description: (
        <>
          <div className="font-semibold text-lg">2. Spot-check results</div>
          <div className="text-sm space-y-3 text-muted-foreground">
            Docent then searches for agent behaviors that match your rubric. You
            can click on each result to see <b>where</b> it was found in each
            transcript, as well as an explanation of <b>why</b> it matched.
          </div>
        </>
      ),
    },
    {
      src: 'https://transluce-videos.s3.us-east-1.amazonaws.com/docent-landing-page/features-3-charts.mp4',
      description: (
        <>
          <div className="font-semibold text-lg">3. Quantify and visualize</div>
          <div className="text-sm space-y-3 text-muted-foreground">
            Finally, visualize quantitative patterns by{' '}
            <b>aggregating, slicing, and filtering</b> using Docent&apos;s
            charts. For example, you can plot the number of reward hacks across
            training steps, or compare the prevalence of reward hacking between
            different models.
          </div>
        </>
      ),
    },
  ];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    setIsSubmitting(true);
    try {
      const { user } = await signup(email.trim(), password.trim()); // Pure API call

      // Set user in context immediately to prevent race condition
      setUser(user);

      // Force a full page navigation to ensure cookie is processed
      const redirectUrl = redirectParam || '/onboarding';
      window.location.href = redirectUrl;
    } catch (error: any) {
      console.error('Failed to sign up:', error);

      // Handle API error responses
      const message =
        error.response?.data?.detail || error.message || 'Signup failed';

      if (
        message.includes('already exists') ||
        error.response?.status === 409
      ) {
        toast.error(
          'A user with this email already exists. Please log in instead.'
        );
      } else {
        toast.error(message);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="h-screen flex flex-col lg:flex-row overflow-y-auto">
      <div className="flex-1 flex items-center justify-center">
        <div className="py-8 px-4 max-w-md flex-1 space-y-6">
          {/* Header */}
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-bold tracking-tight">
              Create your Docent account
            </h1>
            <p className="text-sm text-muted-foreground">
              Enter your email and password to get started
            </p>
          </div>

          {/* Signup Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email Address</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email address"
                disabled={isSubmitting}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                disabled={isSubmitting}
                required
              />
            </div>

            <Button
              type="submit"
              className="w-full"
              size="lg"
              disabled={isSubmitting || !email.trim() || !password.trim()}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating account...
                </>
              ) : (
                'Create Account'
              )}
            </Button>
          </form>

          {/* Link to Login */}
          <div className="text-center">
            <Button
              variant="ghost"
              onClick={() => {
                const loginUrl = redirectParam
                  ? `/login?redirect=${encodeURIComponent(redirectParam)}`
                  : '/login';
                router.push(loginUrl);
              }}
              className="text-sm"
            >
              Already have an account? Sign in
            </Button>
          </div>
        </div>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center p-3 space-y-3">
        <div className="text-primary text-2xl font-bold text-center">
          A quick look at how Docent works
        </div>

        {/* Buttons */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button asChild variant="outline">
            <a
              href="https://docs.transluce.org/en/latest/quickstart"
              target="_blank"
              rel="noopener noreferrer"
            >
              Quickstart guide
            </a>
          </Button>
          <Button asChild variant="outline">
            <a
              href="https://transluce.org/docent/slack"
              target="_blank"
              rel="noopener noreferrer"
            >
              Slack community
            </a>
          </Button>
          <Button asChild variant="outline">
            <a
              href="https://calendly.com/kevin-transluce/30min"
              target="_blank"
              rel="noopener noreferrer"
            >
              Schedule a call
            </a>
          </Button>
          <Button asChild variant="outline">
            <a
              href="mailto:kevin@transluce.org"
              target="_blank"
              rel="noopener noreferrer"
            >
              Email us
            </a>
          </Button>
        </div>

        {/* Video carousel */}
        <div className="w-full max-w-3xl bg-secondary border border-border rounded-lg p-3 space-y-3 shadow-sm">
          <Carousel
            className="w-full"
            opts={{ loop: true }}
            setApi={setCarouselApi}
          >
            <CarouselContent>
              {videoItems.map((item, idx) => (
                <CarouselItem key={idx}>
                  <div className="space-y-3">
                    <div className="space-y-3">{item.description}</div>
                    <div className="relative w-full overflow-hidden rounded-lg border border-border">
                      <div className="pt-[56.25%]"></div>
                      <video
                        className="absolute inset-0 w-full h-full object-cover"
                        autoPlay
                        muted
                        playsInline
                        controls={true}
                        onEnded={() => carouselApi?.scrollNext()}
                      >
                        <source src={item.src} type="video/mp4" />
                        Your browser does not support the video tag.
                      </video>
                    </div>
                  </div>
                </CarouselItem>
              ))}
            </CarouselContent>
            {/* <CarouselPrevious className="hidden sm:flex left-2 md:-left-12 lg:-left-16" /> */}
            {/* <CarouselNext className="hidden sm:flex right-2 md:-right-12 lg:-right-16" /> */}
          </Carousel>
          <div className="flex items-center justify-between">
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => carouselApi?.scrollPrev()}
              aria-label="Previous slide"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="text-xs text-muted-foreground">
              {currentSlide + 1} / {totalSlides}
            </div>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => carouselApi?.scrollNext()}
              aria-label="Next slide"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

const SignupPage = () => {
  return (
    <Suspense>
      <SignupPageContent />
    </Suspense>
  );
};

export default SignupPage;
