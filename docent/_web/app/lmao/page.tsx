'use client';


import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';

export default function LmaoPage() {
  return (
    <div className="flex flex-col h-screen">
      <div className="h-16 bg-gray-300">Header</div>
      <ScrollArea>
        <ScrollArea className="h-full w-full">
          <ScrollBar orientation="horizontal" />
          {Array.from({ length: 100 }).map((_, i) => (
            <div
              key={i}
              className={`flex ${i % 2 === 0 ? 'bg-blue-100' : 'bg-green-100'}`}
            >
              {Array.from({ length: 100 }).map((_, j) => (
                <p key={j} className="px-4">
                  {i} {j}
                </p>
              ))}
            </div>
          ))}
        </ScrollArea>
      </ScrollArea>
      {/* <div className="flex-1 flex space-x-3 min-h-0">
        <Card className="h-full flex-1 p-3">
          <div className="flex flex-col h-full space-y-2">container</div>
        </Card>
        <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3">
          <div className="flex flex-col h-full space-y-2">
            <div className="flex-1 overflow-auto bg-blue-100">
              {Array.from({ length: 100 }).map((_, i) => (
                <div key={i} className="flex">
                  {Array.from({ length: 100 }).map((_, j) => (
                    <p key={j} className="px-4">
                      Lots of content...
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>
      <div className="flex-1 overflow-auto bg-blue-100">
        {Array.from({ length: 100 }).map((_, i) => (
          <div key={i} className="flex">
            {Array.from({ length: 100 }).map((_, j) => (
              <p key={j} className="px-4">
                Lots of content...
              </p>
            ))}
          </div>
        ))}
      </div> */}
    </div>
  );
}
