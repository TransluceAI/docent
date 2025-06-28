// export default function TestPage() {
//   return (
//     <div className="h-[50rem] bg-red-500 flex flex-col">
//       <div className="flex-1 bg-blue-500">asdf</div>
//       <div className="flex-1 bg-green-500">asdf</div>
//       <div className="max-h-2/5 bg-yellow-500 overflow-auto">
//         <div className="h-[40rem] bg-cyan-500">yooo lmao</div>
//       </div>
//     </div>
//   );
// }

export default function TestPage() {
  return (
    <div className="h-[50rem] flex flex-col bg-red-500">
      <div className="flex-1 bg-blue-500">asdf</div>
      <div className="flex-1 bg-green-500">asdf</div>

      {/* fixed to max 40 % of the column, scroll when content overflows */}
      <div className="max-h-[40%] overflow-y-auto bg-yellow-500">
        <div className="h-[4rem] bg-cyan-500">yooo lmao</div>
      </div>
    </div>
  );
}
