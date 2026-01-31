'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Calendar,
  Mail,
  MessageCircle,
  Slack,
  Sparkles,
  Users,
  Target,
  Lightbulb,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

import { toast } from 'sonner';
import { apiRestClient } from '@/app/services/apiService';

const FRAMEWORK_OPTIONS = [
  { id: 'langchain', label: 'LangChain' },
  { id: 'inspect', label: 'Inspect' },
  { id: 'llamaindex', label: 'LlamaIndex' },
  { id: 'autogen', label: 'AutoGen' },
  { id: 'crewai', label: 'CrewAI' },
  { id: 'haystack', label: 'Haystack' },
  { id: 'semantic_kernel', label: 'Semantic Kernel' },
  { id: 'openai_agents', label: 'OpenAI Agents SDK' },
  { id: 'custom', label: 'Custom Framework' },
  { id: 'none', label: 'None' },
  { id: 'other', label: 'Other' },
];

const PROVIDER_OPTIONS = [
  { id: 'openai', label: 'OpenAI' },
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'google', label: 'Google' },
  { id: 'azure', label: 'Azure' },
  { id: 'bedrock', label: 'Bedrock' },
  { id: 'xai', label: 'xAI' },
  { id: 'mistral', label: 'Mistral' },
  { id: 'perplexity', label: 'Perplexity' },
  { id: 'cerebras', label: 'Cerebras' },
  { id: 'vllm', label: 'vLLM Self-Host' },
  { id: 'together', label: 'Together' },
  { id: 'groq', label: 'Groq' },
  { id: 'other', label: 'Other' },
];

interface OnboardingData {
  institution: string;
  task: string;
  helpType: string;
  frameworks: string[];
  otherFrameworkText: string;
  providers: string[];
  otherProviderText: string;
  discoverySource: string;
}

export default function OnboardingPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectParam = searchParams.get('redirect') || '';
  const stepParam = searchParams.get('step');
  const [currentStep, setCurrentStep] = useState(
    stepParam ? parseInt(stepParam) : 1
  );
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [onboardingData, setOnboardingData] = useState<OnboardingData>({
    institution: '',
    task: '',
    helpType: '',
    frameworks: [],
    otherFrameworkText: '',
    providers: [],
    otherProviderText: '',
    discoverySource: '',
  });

  const totalSteps = 5;

  const handleNext = () => {
    if (currentStep < totalSteps) {
      const nextStep = currentStep + 1;
      setCurrentStep(nextStep);
      // Update browser history
      router.push(`/onboarding?step=${nextStep}`, { scroll: false });
    } else {
      // Complete onboarding and redirect to dashboard
      handleCompleteOnboarding();
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      const prevStep = currentStep - 1;
      setCurrentStep(prevStep);
      // Update browser history
      router.push(`/onboarding?step=${prevStep}`, { scroll: false });
    }
  };

  // Initialize URL with current step if not present
  useEffect(() => {
    const stepParam = searchParams.get('step');
    if (!stepParam && currentStep === 1) {
      // Set initial URL without triggering navigation
      router.push('/onboarding?step=1', { scroll: false });
    }
  }, []);

  // Handle URL changes (browser back/forward navigation)
  useEffect(() => {
    const stepParam = searchParams.get('step');
    if (stepParam) {
      const step = parseInt(stepParam);
      if (step >= 1 && step <= totalSteps && step !== currentStep) {
        setCurrentStep(step);
      }
    } else if (currentStep !== 1) {
      // If no step param but we're not on step 1, go to step 1
      setCurrentStep(1);
    }
  }, [searchParams, currentStep, totalSteps]);

  // Reset scroll to top when step changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [currentStep]);

  const handleCompleteOnboarding = async () => {
    try {
      const frameworksData = {
        selected: onboardingData.frameworks,
        other: onboardingData.otherFrameworkText
          ? [onboardingData.otherFrameworkText]
          : [],
      };

      const providersData = {
        selected: onboardingData.providers,
        other: onboardingData.otherProviderText
          ? [onboardingData.otherProviderText]
          : [],
      };

      // Save onboarding data to backend
      await apiRestClient.post('/onboarding', {
        institution: onboardingData.institution || null,
        task: onboardingData.task || null,
        help_type: onboardingData.helpType || null,
        frameworks: frameworksData,
        providers: providersData,
        discovery_source: onboardingData.discoverySource || null,
      });

      toast.success('Your account has been set up successfully.');
      const redirectUrl = redirectParam || '/dashboard';
      router.push(redirectUrl);
    } catch (error) {
      console.error('Failed to complete onboarding:', error);
      toast.error('Failed to complete onboarding. Please try again.');
    }
  };

  const updateOnboardingData = (
    field: keyof OnboardingData,
    value: string | string[]
  ) => {
    setOnboardingData((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  // Reusable component for multi-select steps
  const renderMultiSelectStep = (
    title: string,
    description: string,
    options: Array<{ id: string; label: string }>,
    selectedItems: string[],
    otherText: string,
    otherTextField: keyof OnboardingData,
    itemsField: keyof OnboardingData,
    icon: React.ReactNode
  ) => (
    <div className="space-y-8">
      {/* Header */}
      <div className="text-center space-y-4">
        <div className="flex justify-center mb-4">
          <div className="bg-gray-100 dark:bg-gray-800 rounded-full p-3">
            {icon}
          </div>
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
          {title}
        </h2>
        <p className="text-lg text-gray-600 dark:text-gray-400 max-w-2xl mx-auto">
          {description}
        </p>
      </div>

      {/* Options Grid */}
      <div className="grid grid-cols-2 gap-3 max-w-2xl mx-auto">
        {options.map((option) => {
          // Special handling for "Other" option
          if (option.id === 'other') {
            return (
              <Card
                key={option.id}
                className={`cursor-pointer transition-all hover:shadow-md border col-span-2 ${
                  selectedItems.includes(option.label)
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-gray-700'
                }`}
                onClick={() => {
                  if (selectedItems.includes(option.label)) {
                    // Remove if already selected - preserve custom text
                    const updatedItems = selectedItems.filter(
                      (f) => f !== option.label
                    );
                    updateOnboardingData(itemsField, updatedItems);
                    // Keep the custom text for later restoration
                  } else {
                    // Add if not selected
                    const updatedItems = [...selectedItems, option.label];
                    updateOnboardingData(itemsField, updatedItems);
                  }
                }}
              >
                <CardContent className="p-2">
                  {selectedItems.includes(option.label) ? (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="font-medium text-gray-900 dark:text-white text-sm">
                          {option.label}
                        </h3>
                        <div className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center">
                          <div className="w-2 h-2 bg-white rounded-full"></div>
                        </div>
                      </div>
                      <Input
                        placeholder="Please specify..."
                        value={otherText}
                        onChange={(e) => {
                          updateOnboardingData(otherTextField, e.target.value);
                        }}
                        className="bg-gray-25 dark:bg-gray-900 border-gray-200 dark:border-gray-600"
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                      />
                    </div>
                  ) : (
                    <div className="flex items-center justify-between">
                      <h3 className="font-medium text-gray-900 dark:text-white text-sm">
                        {option.label}
                      </h3>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          }

          // Regular options
          return (
            <Card
              key={option.id}
              className={`cursor-pointer transition-all hover:shadow-md border ${
                selectedItems.includes(option.label)
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                  : 'border-gray-200 dark:border-gray-700'
              }`}
              onClick={() => {
                if (selectedItems.includes(option.label)) {
                  // Remove if already selected
                  const updatedItems = selectedItems.filter(
                    (f) => f !== option.label
                  );
                  updateOnboardingData(itemsField, updatedItems);
                } else {
                  // Add if not selected
                  const updatedItems = [...selectedItems, option.label];
                  updateOnboardingData(itemsField, updatedItems);
                }
              }}
            >
              <CardContent className="p-2">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-white text-sm">
                      {option.label}
                    </h3>
                  </div>
                  {selectedItems.includes(option.label) && (
                    <div className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center">
                      <div className="w-2 h-2 bg-white rounded-full"></div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );

  const renderStep1 = () => (
    <div className="space-y-8">
      {/* Simple Header */}
      <div className="text-center space-y-4">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">
          Welcome to Docent
        </h1>
        <p className="text-lg text-gray-600 dark:text-gray-400 max-w-2xl mx-auto">
          Help us make Docent better by sharing how you plan to use the
          platform.
        </p>
      </div>

      {/* Simple Form */}
      <div className="space-y-6 max-w-2xl mx-auto">
        <div className="space-y-2">
          <Label
            htmlFor="institution"
            className="text-base font-medium text-gray-900 dark:text-white"
          >
            What institution are you with?
          </Label>
          <Input
            id="institution"
            value={onboardingData.institution}
            onChange={(e) =>
              updateOnboardingData('institution', e.target.value)
            }
            placeholder="e.g., Stanford University, Google, Independent Researcher"
            className="text-base border-gray-300 dark:border-gray-600 focus:ring-2 focus:ring-gray-500 focus:border-gray-500"
          />
        </div>

        <div className="space-y-2">
          <Label
            htmlFor="task"
            className="text-base font-medium text-gray-900 dark:text-white"
          >
            What is your task?
          </Label>
          <Textarea
            id="task"
            value={onboardingData.task}
            onChange={(e) => updateOnboardingData('task', e.target.value)}
            placeholder="e.g., Evaluating AI agents, Analyzing conversation transcripts, Building evaluation datasets"
            rows={4}
            className="text-base border-gray-300 dark:border-gray-600 focus:ring-2 focus:ring-gray-500 focus:border-gray-500 resize-none"
          />
        </div>

        <div className="space-y-2">
          <Label
            htmlFor="helpType"
            className="text-base font-medium text-gray-900 dark:text-white"
          >
            How can Docent help?
          </Label>
          <Textarea
            id="helpType"
            value={onboardingData.helpType}
            onChange={(e) => updateOnboardingData('helpType', e.target.value)}
            placeholder="e.g., Judge refinement, Behavior discovery, Automated evaluation"
            rows={4}
            className="text-base border-gray-300 dark:border-gray-600 focus:ring-2 focus:ring-gray-500 focus:border-gray-500 resize-none"
          />
        </div>

        <div className="space-y-2">
          <Label
            htmlFor="discoverySource"
            className="text-base font-medium text-gray-900 dark:text-white"
          >
            How did you find out about Docent?
          </Label>
          <Input
            id="discoverySource"
            value={onboardingData.discoverySource}
            onChange={(e) =>
              updateOnboardingData('discoverySource', e.target.value)
            }
            placeholder="e.g., Colleague recommendation, Search, Social media, Conference"
            className="text-base border-gray-300 dark:border-gray-600 focus:ring-2 focus:ring-gray-500 focus:border-gray-500"
          />
        </div>
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="space-y-8">
      {/* Simple Header */}
      <div className="text-center space-y-4">
        <div className="flex justify-center mb-4">
          <div className="bg-gray-100 dark:bg-gray-800 rounded-full p-3">
            <Users className="h-6 w-6 text-gray-600 dark:text-gray-400" />
          </div>
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
          Join Our Community
        </h2>
        <p className="text-lg text-gray-600 dark:text-gray-400 max-w-2xl mx-auto">
          Connect with fellow researchers and get personalized support from our
          team
        </p>
      </div>

      {/* Simple Community Cards */}
      <div className="grid gap-4 max-w-3xl mx-auto">
        <Card className="border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white flex items-center gap-2">
              <Slack className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              Join our Slack community
            </CardTitle>
            <CardDescription className="text-gray-600 dark:text-gray-400">
              Connect with other researchers, share insights, and get help from
              our team in real-time
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-end">
            <Button
              variant="outline"
              className="border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              onClick={() =>
                window.open('https://transluce.org/docent/slack', '_blank')
              }
            >
              Join Docent Community Slack
            </Button>
          </CardContent>
        </Card>

        <Card className="border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white flex items-center gap-2">
              <Calendar className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              Book a personalized demo
            </CardTitle>
            <CardDescription className="text-gray-600 dark:text-gray-400">
              Schedule a one-on-one consultation with our team to explore how
              Docent can accelerate your research
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-end">
            <Button
              variant="outline"
              className="border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
              onClick={() =>
                window.open(
                  'https://calendly.com/kevin-transluce/30min',
                  '_blank'
                )
              }
            >
              Schedule Call
            </Button>
          </CardContent>
        </Card>

        <Card className="border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white flex items-center gap-2">
              <MessageCircle className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              Email our team
            </CardTitle>
            <CardDescription className="text-gray-600 dark:text-gray-400">
              Have questions or need support? Our team is here to help you
              succeed
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2">
              <Mail className="h-4 w-4 text-gray-500 dark:text-gray-400" />
              <span className="text-sm text-gray-700 dark:text-gray-300">
                info@transluce.org
              </span>
            </div>
            {/* <div className="flex items-center gap-2">
              <Phone className="h-4 w-4 text-gray-500 dark:text-gray-400" />
              <span className="text-sm text-gray-700 dark:text-gray-300">
                +1 (555) 123-4567
              </span>
            </div> */}
            <div className="flex justify-end">
              <Button
                variant="outline"
                className="border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={() =>
                  window.open('mailto:info@transluce.org', '_blank')
                }
              >
                Send Email
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );

  const renderStep3 = () =>
    renderMultiSelectStep(
      'Which frameworks do you use?',
      "Select any frameworks you're currently using",
      FRAMEWORK_OPTIONS,
      onboardingData.frameworks,
      onboardingData.otherFrameworkText,
      'otherFrameworkText',
      'frameworks',
      <Sparkles className="h-6 w-6 text-gray-600 dark:text-gray-400" />
    );

  const renderStep4 = () =>
    renderMultiSelectStep(
      'Which providers do you use?',
      "Select any providers you're currently using",
      PROVIDER_OPTIONS,
      onboardingData.providers,
      onboardingData.otherProviderText,
      'otherProviderText',
      'providers',
      <Lightbulb className="h-6 w-6 text-gray-600 dark:text-gray-400" />
    );

  const renderStep5 = () => (
    <div className="space-y-8">
      {/* Simple Header */}
      <div className="text-center space-y-4">
        <div className="flex justify-center mb-4">
          <div className="bg-gray-100 dark:bg-gray-800 rounded-full p-3">
            <Target className="h-6 w-6 text-gray-600 dark:text-gray-400" />
          </div>
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
          Choose Your Path
        </h2>
        <p className="text-lg text-gray-600 dark:text-gray-400 max-w-2xl mx-auto">
          Pick the method that works best for you to get data into Docent
        </p>
      </div>

      {/* Getting Started Cards */}
      <div className="grid gap-6 max-w-4xl mx-auto">
        {/* Trace Your Agents */}
        <Card className="border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white flex items-center gap-2">
              <Lightbulb className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              Option 1: Trace your agents
            </CardTitle>
            <CardDescription className="text-gray-600 dark:text-gray-400">
              Add tracing to your agents to automatically capture conversations
              and metadata
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg">
              <SyntaxHighlighter
                language="python"
                style={oneDark}
                customStyle={{
                  margin: 0,
                  fontSize: '0.875rem',
                }}
                className="text-sm"
              >
                {`from docent.trace import initialize_tracing, agent_run

# Initialize tracing
initialize_tracing("my-collection")

# Use the decorator
@agent_run
def analyze_document(document_text: str):
    response = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": f"Analyze: {document_text}"}]
    )
    return response.choices[0].message.content`}
              </SyntaxHighlighter>
            </div>
            <div className="flex justify-end">
              <Button
                variant="outline"
                className="border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={() =>
                  window.open('https://docs.transluce.org/tracing', '_blank')
                }
              >
                View Tracing Docs
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Drag and Drop Inspect Evals */}
        <Card className="border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white flex items-center gap-2">
              <Building2 className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              Option 2: Drag and drop Inspect evals
            </CardTitle>
            <CardDescription className="text-gray-600 dark:text-gray-400">
              Import evaluation results from Inspect by simply dragging and
              dropping your eval files
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 text-center">
              <video
                className="w-full h-auto rounded-lg shadow-sm"
                autoPlay
                loop
                muted
                playsInline
                controls={false}
              >
                <source
                  src="https://transluce-videos.s3.us-east-1.amazonaws.com/docent-landing-page/inspect-drag-drop.mp4"
                  type="video/mp4"
                />
                Your browser does not support the video tag.
              </video>
            </div>
            {/* <div className="flex justify-end">
              <Button
                variant="outline"
                className="border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={() => window.open('/docs/quickstart', '_blank')}
              >
                Learn More
              </Button>
            </div> */}
          </CardContent>
        </Card>

        {/* Use the SDK */}
        <Card className="border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader>
            <CardTitle className="text-gray-900 dark:text-white flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-gray-600 dark:text-gray-400" />
              Option 3: Use the SDK
            </CardTitle>
            <CardDescription className="text-gray-600 dark:text-gray-400">
              Programmatically upload data and interact with Docent using our
              Python SDK
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg">
              <SyntaxHighlighter
                language="python"
                style={oneDark}
                customStyle={{
                  margin: 0,
                  fontSize: '0.875rem',
                }}
                className="text-sm"
              >
                {`from docent import Docent
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message

# Create client and collection
client = Docent(api_key="your-api-key")
collection_id = client.create_collection("my-evals")

# Create agent run
transcript = Transcript(messages=[
    parse_chat_message({"role": "user", "content": "Hello"}),
    parse_chat_message({"role": "assistant", "content": "Hi there!"})
])

agent_run = AgentRun(
    transcripts=[transcript],
    metadata={"model": "gpt-5", "scores": {"accuracy": 0.95}}
)

# Upload to Docent
client.add_agent_runs(collection_id, [agent_run])`}
              </SyntaxHighlighter>
            </div>
            <div className="flex justify-end">
              <Button
                variant="outline"
                className="border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={() =>
                  window.open('https://docs.transluce.org/', '_blank')
                }
              >
                View SDK Docs
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );

  return (
    <div
      ref={scrollContainerRef}
      className="h-screen bg-gray-50 dark:bg-gray-950 overflow-y-auto"
    >
      <div className="container mx-auto py-12 px-4 max-w-3xl h-full">
        <div className="space-y-12 pb-8">
          {/* Simple Progress Bar */}
          <div className="space-y-3">
            <div className="flex justify-between text-sm text-gray-600 dark:text-gray-400">
              <span>
                Step {currentStep} of {totalSteps}
              </span>
            </div>
            <div className="relative h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
              <div
                className="h-full bg-gray-900 dark:bg-gray-100 transition-all duration-300 ease-in-out rounded-full"
                style={{ width: `${(currentStep / totalSteps) * 100}%` }}
              />
            </div>
          </div>

          {/* Step Content */}
          <div className="space-y-8">
            {currentStep === 1 && renderStep1()}
            {currentStep === 2 && renderStep2()}
            {currentStep === 3 && renderStep3()}
            {currentStep === 4 && renderStep4()}
            {currentStep === 5 && renderStep5()}
          </div>

          {/* Navigation Buttons */}
          <div className="flex justify-between pt-12 border-t border-gray-200 dark:border-gray-700">
            {currentStep > 1 && (
              <Button
                variant="ghost"
                onClick={handleBack}
                className="flex items-center gap-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
            )}
            {currentStep === 1 && <div></div>}

            <Button
              onClick={handleNext}
              className="flex items-center gap-2 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-200"
              size="lg"
            >
              {currentStep === totalSteps ? 'Complete Setup' : 'Continue'}
              {currentStep < totalSteps && <ArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
