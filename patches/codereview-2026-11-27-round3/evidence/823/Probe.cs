using System.Reflection;
using System.Text.Json.Nodes;
var assembly = Assembly.LoadFrom(args[0]);
var method = assembly.GetType("MagnolieOrganizer.Windows.RestoreSelection", throwOnError:true)!
    .GetMethod("Select", BindingFlags.Static | BindingFlags.NonPublic)!;
foreach (var input in args.Skip(1))
{
    var data=JsonNode.Parse(File.ReadAllText(input))!.AsObject();
    var snapshot=data["before"]!.AsObject();
    var current=data["after"]!.AsObject();
    var restored=(JsonObject)method.Invoke(null,new object[]{snapshot,current,new[]{"contacts"},"additive"})!;
    Console.WriteLine(new JsonObject{["file"]=Path.GetFileName(input),["currentCount"]=current["kontakte"]!.AsArray().Count,
        ["restoredCount"]=restored["kontakte"]!.AsArray().Count,["identities"]=new JsonArray(restored["kontakte"]!.AsArray().OfType<JsonObject>()
            .Select(x=>(JsonNode)new JsonObject{["id"]=x["id"]!.DeepClone(),["uid"]=x["uid"]!.DeepClone()}).ToArray())}.ToJsonString());
}
