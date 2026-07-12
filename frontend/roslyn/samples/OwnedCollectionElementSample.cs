// issue #229 — subscribing to an element of a collection the class itself populated.
// A constructor (or a method it calls) fills a this-owned collection FIELD/PROPERTY
// from the class's own factory / a collection initializer, then subscribes to each
// element in a loop. The collection and its elements share the constructing object's
// lifetime, so `element.PropertyChanged += ...` is a collectable self-cycle, not a leak.
// Real-world shape: MaterialDesignInXamlToolkit MainDemo.Wpf ListsAndGridsViewModel.cs:16-17
// (found by the issue #201 oracle sweep).
//
// The exemption is deliberately NARROW: the loop variable must be provably drawn from a
// this-owned member the class populates ITSELF (own construction / own factory), never a
// ctor parameter or an injected/service-located value. The negative controls below pin
// each edge.
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace OwnSamples.OwnedCollection
{
    public class Model
    {
        public event EventHandler? PropertyChanged;
        public void Bump() => PropertyChanged?.Invoke(this, EventArgs.Empty);
    }

    // Injected/service-located source of models — its elements' lifetimes are unknown.
    public interface IModelService
    {
        List<Model> GetData();
    }

    public class ViewModelBase
    {
        protected void OnPropertyChanged(string name) { }
    }

    // POSITIVE (silent): the ListsAndGridsViewModel shape — an own FACTORY fills the
    // property, then a `foreach` over it subscribes each element.
    public class OwnedFactoryViewModel : ViewModelBase
    {
        public ObservableCollection<Model> Items1 { get; set; }

        public OwnedFactoryViewModel()
        {
            Items1 = CreateData();                                   // own factory fills the member
            foreach (var model in Items1)
                model.PropertyChanged += (s, a) => OnPropertyChanged("Items1");  // silent (#229)
        }

        ObservableCollection<Model> CreateData() => new() { new Model(), new Model() };
    }

    // POSITIVE (silent): a FIELD populated by a collection initializer at its own
    // declaration, iterated in the constructor.
    public class InlineNewViewModel : ViewModelBase
    {
        readonly List<Model> _items = new() { new Model() };

        public InlineNewViewModel()
        {
            foreach (var m in _items)
                m.PropertyChanged += OnChanged;                      // silent (#229)
        }

        void OnChanged(object? sender, EventArgs e) { }
    }

    // POSITIVE (silent): the member is assigned `new ObservableCollection<Model>(...)`
    // directly (own construction), then iterated. `this.`-qualified collection access.
    public class DirectNewViewModel : ViewModelBase
    {
        ObservableCollection<Model> _rows;

        public DirectNewViewModel()
        {
            _rows = new ObservableCollection<Model>();
            foreach (var r in this._rows)
                r.PropertyChanged += OnChanged;                      // silent (#229)
        }

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 1 (flagged, REQUIRED): the collection is a FIELD assigned from a ctor
    // PARAMETER — injected, unknown element lifetime — so the subscription stays flagged.
    public class InjectedCollectionViewModel : ViewModelBase
    {
        readonly IEnumerable<Model> _injected;

        public InjectedCollectionViewModel(IEnumerable<Model> injected)
        {
            _injected = injected;
            foreach (var m in _injected)
                m.PropertyChanged += OnChanged;                      // OWN001: injected collection
        }

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 2 (flagged, REQUIRED): the `foreach` iterates a ctor PARAMETER collection
    // directly (not a this-owned member at all).
    public class ParamCollectionViewModel : ViewModelBase
    {
        public ParamCollectionViewModel(IEnumerable<Model> models)
        {
            foreach (var m in models)
                m.PropertyChanged += OnChanged;                      // OWN001: parameter collection
        }

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 3 (flagged): the member is populated from a SERVICE-LOCATED call
    // (`_service.GetData()`) — the elements are produced by an injected service, not the
    // class's own factory, so their lifetime is unknown.
    public class ServiceLocatedViewModel : ViewModelBase
    {
        readonly IModelService _service;
        List<Model> _items;

        public ServiceLocatedViewModel(IModelService service)
        {
            _service = service;
            _items = _service.GetData();
            foreach (var m in _items)
                m.PropertyChanged += OnChanged;                      // OWN001: service-located source
        }

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 4 (flagged): the member is populated by the own factory in the ctor but
    // ALSO reassigned from an injected value elsewhere — its contents at the `+=` are
    // ambiguous, so every population site must be own-produced or the proof is denied.
    public class MixedCollectionViewModel : ViewModelBase
    {
        List<Model> _items;

        public MixedCollectionViewModel()
        {
            _items = CreateData();
            foreach (var m in _items)
                m.PropertyChanged += OnChanged;                      // OWN001: _items also injected below
        }

        public void Replace(List<Model> injected) => _items = injected;

        List<Model> CreateData() => new() { new Model() };

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 5 (flagged, Codex P1): the member is a freshly-`new`d collection but SEEDED
    // from an injected parameter — the collection object is own-constructed, yet its
    // ELEMENTS (which carry the subscribed events) are injected, so it is not owned.
    public class SeededNewViewModel : ViewModelBase
    {
        readonly List<Model> _items;

        public SeededNewViewModel(IEnumerable<Model> injected)
        {
            _items = new List<Model>(injected);
            foreach (var m in _items)
                m.PropertyChanged += OnChanged;                      // OWN001: seeded from injected elements
        }

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 6 (flagged, Codex P1): an own-class factory that FORWARDS an injected
    // service's collection — a same-class call, but its body returns service-located
    // elements of unknown lifetime, so the factory result is not own-produced.
    public class ForwardingFactoryViewModel : ViewModelBase
    {
        readonly IModelService _service;
        List<Model> _items;

        public ForwardingFactoryViewModel(IModelService service)
        {
            _service = service;
            _items = MakeData();
            foreach (var m in _items)
                m.PropertyChanged += OnChanged;                      // OWN001: factory forwards injected data
        }

        List<Model> MakeData() => _service.GetData();

        void OnChanged(object? sender, EventArgs e) { }
    }

    // CONTROL 7 (flagged, CodeRabbit): a PARTIAL class whose own-factory population lives
    // in one declaration but a DISQUALIFYING injected assignment lives in the sibling
    // partial — the population scan must cover every partial of the type, not just the
    // declaration holding the `foreach`.
    public partial class PartialInjectedViewModel : ViewModelBase
    {
        List<Model> _items;

        public PartialInjectedViewModel()
        {
            _items = CreateData();
            foreach (var m in _items)
                m.PropertyChanged += OnChanged;                      // OWN001: _items also injected in the sibling partial

        }

        List<Model> CreateData() => new() { new Model() };

        void OnChanged(object? sender, EventArgs e) { }
    }

    public partial class PartialInjectedViewModel
    {
        public void Seed(List<Model> injected) => _items = injected;   // sibling-partial injected write
    }
}
